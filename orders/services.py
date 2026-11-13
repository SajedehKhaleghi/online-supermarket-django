"""منطق کسب‌وکار سفارش: ثبت اتمیک سفارش، رزرو/آزادسازی موجودی، تایید و تطبیق پرداخت."""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from products.models import Product
from . import zarinpal
from .models import Cart, Order, OrderItem, Payment

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    """خطای قابل نمایش به کاربر هنگام ثبت سفارش (مثل کمبود موجودی)."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("؛ ".join(self.problems))


def get_cart_problems(cart):
    """مشکلات فعلی سبد (محصول غیرفعال یا کمبود موجودی) را بدون قفل برمی‌گرداند؛ برای نمایش در سبد."""
    problems = {}
    for item in cart.items.select_related("product"):
        p = item.product
        if not p.is_active:
            problems[item.id] = f"«{p.name}» دیگر در دسترس نیست."
        elif p.stock < item.quantity:
            problems[item.id] = f"موجودی «{p.name}» فقط {p.stock} عدد است."
    return problems


@transaction.atomic
def create_order_from_cart(user, address, delivery_time):
    """
    سفارش را به‌صورت اتمیک می‌سازد: محصولات قفل می‌شوند (select_for_update)، موجودی و فعال بودن
    بررسی می‌شود، موجودی رزرو (کم) می‌شود و سبد خالی می‌شود. در صورت هر خطا هیچ تغییری ثبت نمی‌شود.
    """
    # قفل سبد: دو درخواست هم‌زمان (دابل‌کلیک) نمی‌توانند از یک سبد دو سفارش بسازند
    cart = Cart.objects.select_for_update().get(user=user)
    items = list(cart.items.select_related("product").order_by("product_id"))
    if not items:
        raise CheckoutError(["سبد خرید شما خالی است."])

    locked = {
        p.id: p
        for p in Product.objects.select_for_update().filter(id__in=[i.product_id for i in items]).order_by("id")
    }

    problems = []
    for item in items:
        product = locked[item.product_id]
        if not product.is_active:
            problems.append(f"«{product.name}» دیگر در دسترس نیست.")
        elif product.stock < item.quantity:
            problems.append(f"موجودی «{product.name}» فقط {product.stock} عدد است.")
    if problems:
        raise CheckoutError(problems)

    total = sum(locked[i.product_id].final_price * i.quantity for i in items)
    order = Order.objects.create(user=user, address=address, delivery_time=delivery_time, total_price=total)
    for item in items:
        product = locked[item.product_id]
        OrderItem.objects.create(
            order=order, product=product, product_name=product.name,
            price=product.final_price, quantity=item.quantity,
        )
        Product.objects.filter(pk=product.pk).update(stock=F("stock") - item.quantity)
    Payment.objects.create(order=order, amount=total)
    cart.items.all().delete()
    return order


def _restore_stock(order):
    for item in order.items.exclude(product__isnull=True):
        Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)


@transaction.atomic
def cancel_order(order):
    """سفارش را لغو و موجودی رزروشده را برمی‌گرداند. اگر قبلاً لغو شده باشد، کاری نمی‌کند."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status == "cancelled":
        return False
    _restore_stock(locked)
    locked.status = "cancelled"
    locked.save(update_fields=["status", "updated_at"])
    payment = getattr(locked, "payment", None)
    if payment and payment.status == "pending":
        payment.status = "failed"
        payment.save(update_fields=["status"])
    order.status = "cancelled"
    return True


@transaction.atomic
def mark_order_paid(order, ref_id):
    """
    پرداخت موفق را (idempotent) ثبت می‌کند.
    اگر سفارش قبلاً منقضی/لغو شده بود (callback دیرهنگام)، تلاش می‌کند موجودی را دوباره رزرو و سفارش را احیا کند.
    خروجی: "paid" | "already_paid" | "paid_but_cancelled"
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)
    payment = locked.payment
    if payment.status == "success":
        return "already_paid"

    result = "paid"
    if locked.status == "cancelled":
        items = list(locked.items.select_related("product"))
        products = {
            p.id: p for p in Product.objects.select_for_update()
            .filter(id__in=[i.product_id for i in items if i.product_id]).order_by("id")
        }
        can_revive = all(
            i.product_id in products and products[i.product_id].stock >= i.quantity for i in items
        )
        if can_revive:
            for i in items:
                Product.objects.filter(pk=i.product_id).update(stock=F("stock") - i.quantity)
            locked.status = "processing"
        else:
            result = "paid_but_cancelled"
            logger.warning("Payment succeeded for cancelled order %s and stock is gone; needs manual refund.", locked.pk)
    else:
        locked.status = "processing"

    payment.status = "success"
    payment.transaction_id = ref_id
    payment.paid_at = timezone.now()
    payment.save(update_fields=["status", "transaction_id", "paid_at"])
    locked.save(update_fields=["status", "updated_at"])
    order.status = locked.status
    return result


def reconcile_payment(payment):
    """
    پرداختی که Authority دارد ولی نتیجه‌اش ثبت نشده (مثلاً کاربر مرورگر را قبل از بازگشت بست)
    را مستقیماً از زرین‌پال استعلام می‌کند. خروجی: وضعیت verify.
    """
    if payment.status == "success":
        return zarinpal.VERIFY_FAILED
    authorities = payment.known_authorities()[: Payment.MAX_AUTHORITIES_TO_CHECK]
    if not authorities:
        return zarinpal.VERIFY_FAILED
    overall = zarinpal.VERIFY_FAILED
    for authority in authorities:
        status, detail = zarinpal.verify_payment(payment.amount, authority)
        if status == zarinpal.VERIFY_SUCCESS:
            mark_order_paid(payment.order, detail)
            return status
        if status == zarinpal.VERIFY_ERROR:
            overall = zarinpal.VERIFY_ERROR   # نتیجه‌ی نامشخص: تا بررسی بعدی لغو نکن
    return overall


def expire_pending_orders(timeout_minutes=None, now=None):
    """سفارش‌های پرداخت‌نشده‌ی قدیمی را (پس از یک تطبیق نهایی با درگاه) لغو می‌کند. خروجی: (لغو شده‌ها, پرداخت‌شده‌ها)"""
    timeout_minutes = settings.PENDING_ORDER_TIMEOUT_MINUTES if timeout_minutes is None else timeout_minutes
    cutoff = (now or timezone.now()) - timedelta(minutes=timeout_minutes)
    cancelled = recovered = 0
    for order in Order.objects.filter(status="pending_payment", created_at__lt=cutoff).select_related("payment"):
        if order.payment.status == "success":
            continue  # پرداخت شده؛ هرگز لغو نشود (حتی اگر وضعیت سفارش دستی به pending برگشته باشد)
        status = reconcile_payment(order.payment)
        if status == zarinpal.VERIFY_SUCCESS:
            recovered += 1
        elif status == zarinpal.VERIFY_ERROR:
            continue  # نتیجه نامشخص؛ دفعه‌ی بعد دوباره بررسی می‌شود
        elif cancel_order(order):
            cancelled += 1
    return cancelled, recovered
