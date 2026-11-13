import random
import string

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from products.models import Product
from . import services, zarinpal
from .forms import CheckoutForm, OrderStatusForm
from .models import Cart, Order, PaymentAuthority


FULFILMENT_STATUSES = {"processing", "shipped", "delivered"}


def staff_required(user):
    return user.is_authenticated and user.is_staff


def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def parse_quantity(raw, default=1):
    """ورودی تعداد را امن به عدد صحیح مثبت تبدیل می‌کند (ورودی نامعتبر → مقدار پیش‌فرض)."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value


def _safe_back(request, fallback):
    referer = request.META.get("HTTP_REFERER")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect(fallback)


# ---------- سبد خرید ----------

@login_required
def cart_view(request):
    cart = get_or_create_cart(request.user)
    items = list(cart.items.select_related("product"))
    problems = services.get_cart_problems(cart)
    return render(request, "orders/cart.html", {
        "cart": cart,
        "items": items,
        "problems": problems,
        "cart_total": sum(i.subtotal for i in items),
        "has_problems": bool(problems),
    })


@login_required
@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    cart = get_or_create_cart(request.user)
    quantity = parse_quantity(request.POST.get("quantity"), default=1)
    if quantity < 1:
        messages.error(request, "تعداد باید حداقل ۱ باشد.")
        return _safe_back(request, "products:home")

    item = cart.items.filter(product=product).first()
    current = item.quantity if item else 0
    if current + quantity > product.stock:
        allowed = max(product.stock - current, 0)
        if allowed == 0:
            if product.stock == 0:
                messages.warning(request, f"«{product.name}» در حال حاضر ناموجود است.")
            else:
                messages.warning(request, f"موجودی «{product.name}» به‌اندازه‌ی تعداد فعلی سبد شماست.")
            return _safe_back(request, "products:home")
        quantity = allowed
        messages.warning(request, f"فقط {allowed} عدد دیگر از «{product.name}» موجود بود و همان مقدار اضافه شد.")
    else:
        messages.success(request, f"{product.name} به سبد خرید اضافه شد.")

    if item:
        item.quantity = current + quantity
        item.save(update_fields=["quantity"])
    else:
        cart.items.create(product=product, quantity=quantity)
    return _safe_back(request, "products:home")


@login_required
@require_POST
def cart_update(request, item_id):
    item = get_object_or_404(cart_items_of(request.user), id=item_id)
    quantity = parse_quantity(request.POST.get("quantity"), default=item.quantity)
    if quantity <= 0:
        item.delete()
    else:
        if quantity > item.product.stock:
            quantity = item.product.stock
            messages.warning(request, f"حداکثر موجودی «{item.product.name}» {quantity} عدد است.")
        if quantity <= 0:
            item.delete()
        else:
            item.quantity = quantity
            item.save(update_fields=["quantity"])
    return redirect("orders:cart")


def cart_items_of(user):
    from .models import CartItem
    return CartItem.objects.filter(cart__user=user).select_related("product")


@login_required
@require_POST
def cart_remove(request, item_id):
    item = get_object_or_404(cart_items_of(request.user), id=item_id)
    item.delete()
    messages.info(request, "محصول از سبد خرید حذف شد.")
    return redirect("orders:cart")


# ---------- ثبت سفارش ----------

@login_required
def checkout_view(request):
    cart = get_or_create_cart(request.user)
    items = list(cart.items.select_related("product"))
    if not items:
        messages.warning(request, "سبد خرید شما خالی است.")
        return redirect("products:product_list")

    problems = services.get_cart_problems(cart)
    if problems:
        for text in problems.values():
            messages.error(request, text)
        return redirect("orders:cart")

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                order = services.create_order_from_cart(
                    request.user, form.cleaned_data["address"], form.cleaned_data["delivery_time"]
                )
            except services.CheckoutError as exc:
                for text in exc.problems:
                    messages.error(request, text)
                return redirect("orders:cart")
            return redirect("orders:payment", order_id=order.id)
    else:
        form = CheckoutForm(initial={"address": request.user.address})

    return render(request, "orders/checkout.html", {
        "form": form, "cart": cart, "items": items,
        "cart_total": sum(i.subtotal for i in items),
    })


# ---------- پرداخت ----------

@login_required
def payment_view(request, order_id):
    """
    شروع پرداخت: کاربر را به درگاه زرین‌پال هدایت می‌کند.
    حالت شبیه‌سازی فقط وقتی settings.ALLOW_PAYMENT_SIMULATION فعال باشد (فقط DEBUG) در دسترس است.
    """
    order = get_object_or_404(Order, id=order_id, user=request.user)
    payment = order.payment

    if payment.status == "success":
        return redirect("orders:order_detail", order_id=order.id)
    if not order.is_payable:
        messages.error(request, "این سفارش قابل پرداخت نیست.")
        return redirect("orders:order_detail", order_id=order.id)

    callback_url = request.build_absolute_uri(reverse("orders:payment_verify", args=[order.id]))
    try:
        authority, gateway_url = zarinpal.request_payment(
            amount_toman=payment.amount,
            description=f"پرداخت سفارش #{order.id} - سوپر مارکت آنلاین",
            callback_url=callback_url,
            mobile=request.user.phone_number,
        )
    except zarinpal.ZarinpalError as exc:
        if settings.ALLOW_PAYMENT_SIMULATION:
            messages.warning(request, "اتصال به درگاه زرین‌پال ممکن نشد؛ حالت آزمایشی (فقط توسعه) فعال است.")
            return render(request, "orders/payment_simulate.html", {"order": order, "payment": payment, "error": str(exc)})
        messages.error(request, "اتصال به درگاه پرداخت برقرار نشد. لطفاً چند لحظه بعد دوباره تلاش کنید.")
        return redirect("orders:order_detail", order_id=order.id)

    PaymentAuthority.objects.get_or_create(payment=payment, authority=authority)
    payment.authority = authority
    payment.status = "pending"
    payment.save(update_fields=["authority", "status"])
    return redirect(gateway_url)


@login_required
@require_POST
def payment_simulate_confirm(request, order_id):
    """شبیه‌سازی پرداخت: فقط در حالت توسعه (DEBUG) و برای سفارش در انتظار پرداخت."""
    if not settings.ALLOW_PAYMENT_SIMULATION:
        raise Http404
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if not order.is_payable or order.payment.status == "success":
        messages.error(request, "این سفارش قابل پرداخت نیست.")
        return redirect("orders:order_detail", order_id=order.id)

    ref = "".join(random.choices(string.digits, k=12))
    services.mark_order_paid(order, ref)
    messages.success(request, "پرداخت (آزمایشی) با موفقیت انجام شد.")
    return redirect("orders:order_detail", order_id=order.id)


@login_required
def payment_verify_view(request, order_id):
    """کاربر پس از پرداخت در زرین‌پال، به این مسیر بازمی‌گردد (callback)."""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    payment = order.payment

    if payment.status == "success":
        return redirect("orders:order_detail", order_id=order.id)

    authority_param = request.GET.get("Authority", "")
    # Authority برگشتی باید یکی از کدهایی باشد که برای «همین» سفارش گرفته‌ایم (نه مال سفارش دیگر)؛
    # فقط آخرین کد قبول نیست چون کاربر ممکن است با تب/کد قدیمی‌تر پرداخت کرده باشد.
    if not authority_param or authority_param not in payment.known_authorities():
        messages.error(request, "اطلاعات بازگشت از درگاه معتبر نیست.")
        return redirect("orders:order_detail", order_id=order.id)

    if request.GET.get("Status") != "OK":
        # انصراف روی یک کد قدیمی نباید وضعیت پرداختِ جاری را خراب کند
        if authority_param == payment.authority:
            payment.status = "failed"
            payment.save(update_fields=["status"])
        messages.error(request, "پرداخت توسط شما لغو شد یا ناموفق بود. می‌توانید دوباره پرداخت کنید.")
        return redirect("orders:order_detail", order_id=order.id)

    status, detail = zarinpal.verify_payment(amount_toman=payment.amount, authority=authority_param)
    if status == zarinpal.VERIFY_SUCCESS:
        result = services.mark_order_paid(order, detail)
        if result == "paid_but_cancelled":
            messages.warning(
                request,
                f"پرداخت شما ثبت شد (کد رهگیری: {detail}) اما سفارش به دلیل اتمام موجودی لغو شده بود. "
                "لطفاً با پشتیبانی تماس بگیرید تا مبلغ برگشت داده شود.",
            )
        else:
            messages.success(request, f"پرداخت با موفقیت انجام شد. کد رهگیری: {detail}")
    elif status == zarinpal.VERIFY_ERROR:
        # نتیجه نامشخص است؛ وضعیت را «معلق» نگه می‌داریم و دستور reconcile_payments بعداً بررسی می‌کند
        messages.warning(
            request,
            "تایید نهایی پرداخت هنوز ممکن نشد. اگر مبلغ از حساب شما کسر شده، تا چند دقیقه‌ی دیگر خودکار تایید می‌شود.",
        )
    else:
        if authority_param == payment.authority:
            payment.status = "failed"
            payment.save(update_fields=["status"])
        messages.error(request, f"پرداخت تایید نشد: {detail}")

    return redirect("orders:order_detail", order_id=order.id)


# ---------- سفارش‌های کاربر ----------

@login_required
def order_list_view(request):
    orders = Order.objects.filter(user=request.user)
    page_obj = Paginator(orders, 10).get_page(request.GET.get("page"))
    return render(request, "orders/order_list.html", {"orders": page_obj, "page_obj": page_obj})


@login_required
def order_detail_view(request, order_id):
    order = get_object_or_404(Order.objects.select_related("payment"), id=order_id, user=request.user)
    return render(request, "orders/order_detail.html", {"order": order})


@login_required
@require_POST
def order_cancel_view(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status != "pending_payment":
        messages.error(request, "فقط سفارش‌های پرداخت‌نشده قابل لغو هستند.")
    else:
        services.cancel_order(order)
        messages.info(request, "سفارش لغو شد و موجودی آزاد گردید.")
    return redirect("orders:order_detail", order_id=order.id)


# ---------- پنل مدیریت سفارش‌ها ----------

@user_passes_test(staff_required)
def admin_order_list(request):
    orders = Order.objects.select_related("user", "payment")
    status_filter = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()
    if status_filter:
        orders = orders.filter(status=status_filter)
    if query:
        cond = Q(user__username__icontains=query) | Q(user__phone_number__icontains=query)
        try:
            order_id = int(query)
        except ValueError:
            order_id = None
        if order_id is not None and 0 <= order_id < 2**63:
            cond |= Q(id=order_id)
        orders = orders.filter(cond)
    page_obj = Paginator(orders, 20).get_page(request.GET.get("page"))
    return render(request, "orders/admin/order_list.html", {
        "orders": page_obj, "page_obj": page_obj, "status_filter": status_filter,
        "query": query, "status_choices": Order.STATUS_CHOICES,
    })


@user_passes_test(staff_required)
def admin_order_detail(request, order_id):
    order = get_object_or_404(Order.objects.select_related("user", "payment"), id=order_id)
    if request.method == "POST":
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            new_status = form.cleaned_data["status"]
            previous = Order.objects.get(pk=order.pk).status
            if previous == "cancelled" and new_status != "cancelled":
                messages.error(request, "سفارش لغوشده قابل بازگشایی نیست (موجودی آزاد شده است).")
            elif new_status == "pending_payment" and order.payment.status == "success":
                # سفارشِ پرداخت‌شده اگر به «در انتظار پرداخت» برگردد، دستور expire_pending_orders آن را لغو
                # و موجودی را آزاد می‌کند، در حالی که پول دریافت شده است.
                messages.error(request, "این سفارش پرداخت شده است و به «در انتظار پرداخت» برنمی‌گردد.")
            elif new_status in FULFILMENT_STATUSES and order.payment.status != "success":
                messages.error(request, "این سفارش پرداخت نشده است؛ نمی‌توان آن را آماده/ارسال/تحویل کرد.")
            elif new_status == "cancelled":
                services.cancel_order(order)
                if order.payment.status == "success":
                    messages.warning(request, "سفارش لغو و موجودی بازگردانده شد؛ اما پرداخت این سفارش موفق بوده است — "
                                              "مبلغ را باید به مشتری برگردانید (کد رهگیری: "
                                              f"{order.payment.transaction_id or '—'}).")
                else:
                    messages.success(request, "سفارش لغو و موجودی بازگردانده شد.")
                return redirect("orders:admin_order_detail", order_id=order.id)
            else:
                form.save()
                messages.success(request, "وضعیت سفارش بروزرسانی شد.")
                return redirect("orders:admin_order_detail", order_id=order.id)
        order = Order.objects.select_related("user", "payment").get(pk=order.pk)
        form = OrderStatusForm(instance=order)
    else:
        form = OrderStatusForm(instance=order)
    return render(request, "orders/admin/order_detail.html", {"order": order, "form": form})
