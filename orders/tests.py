from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from products.models import Category, Product
from . import services, zarinpal
from .models import Cart, Order, Payment


class BaseShopTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", password="pw-12345-xx", phone_number="09120000100", is_active=True)
        self.other = User.objects.create_user("o", password="pw-12345-xx", phone_number="09120000101")
        self.staff = User.objects.create_user("s", password="pw-12345-xx", phone_number="09120000102", is_staff=True)
        self.cat = Category.objects.create(name="c")
        self.milk = Product.objects.create(category=self.cat, name="milk", description="d", price=10000, stock=5)
        self.rice = Product.objects.create(category=self.cat, name="rice", description="d", price=50000, stock=3,
                                           discount_percent=10)
        self.client.force_login(self.user)

    def add_to_cart(self, product, qty):
        Cart.objects.get(user=self.user).items.create(product=product, quantity=qty)

    def make_order(self, **kw):
        self.add_to_cart(self.milk, kw.pop("milk", 2))
        return services.create_order_from_cart(self.user, "تهران", "فردا")


class CartTests(BaseShopTest):
    def post_add(self, product, qty):
        return self.client.post(reverse("orders:cart_add", args=[product.id]), {"quantity": qty})

    def test_mutations_require_post(self):
        self.assertEqual(self.client.get(reverse("orders:cart_add", args=[self.milk.id])).status_code, 405)
        self.add_to_cart(self.milk, 1)
        item = Cart.objects.get(user=self.user).items.get()
        self.assertEqual(self.client.get(reverse("orders:cart_remove", args=[item.id])).status_code, 405)
        self.assertEqual(self.client.get(reverse("orders:cart_update", args=[item.id])).status_code, 405)

    def test_login_required(self):
        self.client.logout()
        response = self.client.post(reverse("orders:cart_add", args=[self.milk.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_add_normal(self):
        self.post_add(self.milk, 2)
        self.assertEqual(Cart.objects.get(user=self.user).items.get().quantity, 2)

    def test_garbage_quantity_defaults_to_one(self):
        self.post_add(self.milk, "abc")
        self.assertEqual(Cart.objects.get(user=self.user).items.get().quantity, 1)

    def test_negative_or_zero_quantity_rejected(self):
        self.post_add(self.milk, -3)
        self.post_add(self.milk, 0)
        self.assertFalse(Cart.objects.get(user=self.user).items.exists())

    def test_quantity_clamped_to_stock(self):
        self.post_add(self.milk, 99)
        self.assertEqual(Cart.objects.get(user=self.user).items.get().quantity, 5)

    def test_repeated_adds_cannot_exceed_stock(self):
        self.post_add(self.milk, 4)
        self.post_add(self.milk, 4)
        self.assertEqual(Cart.objects.get(user=self.user).items.get().quantity, 5)

    def test_inactive_product_cannot_be_added(self):
        self.milk.is_active = False
        self.milk.save()
        self.assertEqual(self.post_add(self.milk, 1).status_code, 404)

    def test_update_clamps_and_zero_deletes(self):
        self.add_to_cart(self.milk, 1)
        item = Cart.objects.get(user=self.user).items.get()
        self.client.post(reverse("orders:cart_update", args=[item.id]), {"quantity": "50"})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)
        self.client.post(reverse("orders:cart_update", args=[item.id]), {"quantity": "0"})
        self.assertFalse(Cart.objects.get(user=self.user).items.exists())

    def test_cannot_touch_other_users_items(self):
        other_cart = Cart.objects.get(user=self.other)
        item = other_cart.items.create(product=self.milk, quantity=1)
        self.assertEqual(self.client.post(reverse("orders:cart_remove", args=[item.id])).status_code, 404)

    def test_cart_totals_use_discounted_price(self):
        self.add_to_cart(self.rice, 2)  # 45000 * 2
        response = self.client.get(reverse("orders:cart"))
        self.assertEqual(response.context["cart_total"], 90000)


class CheckoutTests(BaseShopTest):
    def test_checkout_reserves_stock_and_clears_cart(self):
        self.add_to_cart(self.milk, 2)
        self.add_to_cart(self.rice, 1)
        order = services.create_order_from_cart(self.user, "addr", "t")
        self.milk.refresh_from_db(); self.rice.refresh_from_db()
        self.assertEqual((self.milk.stock, self.rice.stock), (3, 2))
        self.assertEqual(order.total_price, 2 * 10000 + 45000)
        self.assertEqual(order.payment.amount, order.total_price)
        self.assertFalse(Cart.objects.get(user=self.user).items.exists())
        self.assertEqual(order.status, "pending_payment")

    def test_insufficient_stock_is_atomic(self):
        self.add_to_cart(self.milk, 2)
        self.add_to_cart(self.rice, 3)
        Product.objects.filter(pk=self.rice.pk).update(stock=1)  # بعد از افزودن به سبد کم شد
        with self.assertRaises(services.CheckoutError):
            services.create_order_from_cart(self.user, "addr", "t")
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.stock, 5)               # موجودی هیچ‌چیز تغییر نکرده
        self.assertFalse(Order.objects.exists())            # سفارش نیمه‌کاره نمانده
        self.assertEqual(Cart.objects.get(user=self.user).items.count(), 2)  # سبد دست‌نخورده

    def test_inactive_product_blocks_checkout(self):
        self.add_to_cart(self.milk, 1)
        Product.objects.filter(pk=self.milk.pk).update(is_active=False)
        with self.assertRaises(services.CheckoutError):
            services.create_order_from_cart(self.user, "a", "t")

    def test_empty_cart(self):
        with self.assertRaises(services.CheckoutError):
            services.create_order_from_cart(self.user, "a", "t")

    def test_checkout_view_redirects_to_cart_on_problems(self):
        self.add_to_cart(self.milk, 3)
        Product.objects.filter(pk=self.milk.pk).update(stock=1)
        response = self.client.get(reverse("orders:checkout"))
        self.assertRedirects(response, reverse("orders:cart"))

    def test_checkout_view_full_flow(self):
        self.add_to_cart(self.milk, 1)
        response = self.client.post(reverse("orders:checkout"), {"address": "تهران", "delivery_time": "فردا"})
        order = Order.objects.get()
        self.assertRedirects(response, reverse("orders:payment", args=[order.id]), fetch_redirect_response=False)

    def test_price_is_snapshotted(self):
        order = self.make_order(milk=1)
        Product.objects.filter(pk=self.milk.pk).update(price=99999)
        self.assertEqual(order.items.get().price, 10000)


@override_settings(ALLOW_PAYMENT_SIMULATION=False)
class PaymentSimulationDisabledTests(BaseShopTest):
    def test_simulate_endpoint_is_404_and_does_not_pay(self):
        order = self.make_order()
        response = self.client.post(reverse("orders:payment_simulate", args=[order.id]))
        self.assertEqual(response.status_code, 404)
        order.refresh_from_db()
        self.assertEqual(order.status, "pending_payment")
        self.assertEqual(order.payment.status, "pending")

    def test_gateway_down_does_not_fall_back_to_simulation(self):
        order = self.make_order()
        with mock.patch("orders.views.zarinpal.request_payment", side_effect=zarinpal.ZarinpalError("down")):
            response = self.client.get(reverse("orders:payment", args=[order.id]))
        self.assertRedirects(response, reverse("orders:order_detail", args=[order.id]))


@override_settings(ALLOW_PAYMENT_SIMULATION=True)
class PaymentSimulationEnabledTests(BaseShopTest):
    def test_simulate_marks_paid(self):
        order = self.make_order()
        self.client.post(reverse("orders:payment_simulate", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, "processing")
        self.assertEqual(order.payment.status, "success")

    def test_simulate_requires_post(self):
        order = self.make_order()
        self.assertEqual(self.client.get(reverse("orders:payment_simulate", args=[order.id])).status_code, 405)

    def test_simulate_not_allowed_on_cancelled_order(self):
        order = self.make_order()
        services.cancel_order(order)
        self.client.post(reverse("orders:payment_simulate", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, "cancelled")
        self.assertEqual(order.payment.status, "failed")


class GatewayFlowTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.order = self.make_order()

    def start_payment(self):
        with mock.patch("orders.views.zarinpal.request_payment", return_value=("AUTH123", "https://gw/AUTH123")):
            return self.client.get(reverse("orders:payment", args=[self.order.id]))

    def callback(self, status="OK", authority="AUTH123"):
        return self.client.get(
            reverse("orders:payment_verify", args=[self.order.id]), {"Status": status, "Authority": authority}
        )

    def test_start_redirects_to_gateway_and_stores_authority(self):
        response = self.start_payment()
        self.assertEqual(response.url, "https://gw/AUTH123")
        self.order.payment.refresh_from_db()
        self.assertEqual(self.order.payment.authority, "AUTH123")

    def test_verify_success(self):
        self.start_payment()
        with mock.patch("orders.views.zarinpal.verify_payment", return_value=(zarinpal.VERIFY_SUCCESS, "REF9")):
            self.callback()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "processing")
        self.assertEqual(self.order.payment.transaction_id, "REF9")
        self.assertIsNotNone(self.order.payment.paid_at)

    def test_verify_is_idempotent(self):
        self.start_payment()
        with mock.patch("orders.views.zarinpal.verify_payment", return_value=(zarinpal.VERIFY_SUCCESS, "REF9")) as v:
            self.callback()
            self.callback()
        self.assertEqual(v.call_count, 1)

    def test_authority_mismatch_is_rejected_without_calling_gateway(self):
        self.start_payment()
        with mock.patch("orders.views.zarinpal.verify_payment") as v:
            self.callback(authority="SOMEONE-ELSES")
        v.assert_not_called()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending_payment")

    def test_user_cancelled_at_gateway_allows_retry(self):
        self.start_payment()
        self.callback(status="NOK")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment.status, "failed")
        self.assertEqual(self.order.status, "pending_payment")
        self.assertEqual(self.start_payment().url, "https://gw/AUTH123")  # دوباره قابل پرداخت است

    def test_network_error_keeps_payment_pending(self):
        self.start_payment()
        with mock.patch("orders.views.zarinpal.verify_payment", return_value=(zarinpal.VERIFY_ERROR, "timeout")):
            self.callback()
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment.status, "pending")
        self.assertEqual(self.order.status, "pending_payment")

    def test_gateway_rejection_marks_failed(self):
        self.start_payment()
        with mock.patch("orders.views.zarinpal.verify_payment", return_value=(zarinpal.VERIFY_FAILED, "{-51}")):
            self.callback()
        self.order.payment.refresh_from_db()
        self.assertEqual(self.order.payment.status, "failed")

    def test_other_user_cannot_use_my_order(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("orders:payment", args=[self.order.id])).status_code, 404)
        self.assertEqual(self.callback().status_code, 404)


class ZarinpalClientTests(TestCase):
    def fake(self, payload):
        resp = mock.Mock()
        resp.json.return_value = payload
        return resp

    def test_verify_success_and_already_verified(self):
        for code in (100, 101):
            with mock.patch("orders.zarinpal.requests.post", return_value=self.fake({"data": {"code": code, "ref_id": 77}})):
                self.assertEqual(zarinpal.verify_payment(1000, "A"), (zarinpal.VERIFY_SUCCESS, "77"))

    def test_verify_failure_with_list_data(self):
        # زرین‌پال در خطا «data» را به‌صورت لیست خالی برمی‌گرداند
        payload = {"data": [], "errors": {"code": -51}}
        with mock.patch("orders.zarinpal.requests.post", return_value=self.fake(payload)):
            self.assertEqual(zarinpal.verify_payment(1000, "A")[0], zarinpal.VERIFY_FAILED)

    def test_verify_network_error(self):
        import requests
        with mock.patch("orders.zarinpal.requests.post", side_effect=requests.Timeout("x")):
            self.assertEqual(zarinpal.verify_payment(1000, "A")[0], zarinpal.VERIFY_ERROR)

    def test_amount_converted_to_rial(self):
        with mock.patch("orders.zarinpal.requests.post", return_value=self.fake({"data": {"code": 100, "ref_id": 1}})) as post:
            zarinpal.verify_payment(1000, "A")
        self.assertEqual(post.call_args[1]["json"]["amount"], 10000)


class CancelAndExpiryTests(BaseShopTest):
    def test_cancel_restores_stock_once(self):
        order = self.make_order(milk=2)
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.stock, 3)
        self.assertTrue(services.cancel_order(order))
        self.assertFalse(services.cancel_order(order))  # بار دوم موجودی دوباره اضافه نمی‌شود
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.stock, 5)

    def test_user_can_cancel_pending_order_via_view(self):
        order = self.make_order()
        self.client.post(reverse("orders:order_cancel", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, "cancelled")

    def test_user_cannot_cancel_paid_order(self):
        order = self.make_order()
        services.mark_order_paid(order, "R")
        self.client.post(reverse("orders:order_cancel", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, "processing")

    def test_cancel_requires_post(self):
        order = self.make_order()
        self.assertEqual(self.client.get(reverse("orders:order_cancel", args=[order.id])).status_code, 405)

    def test_expire_cancels_old_pending_orders(self):
        old = self.make_order(milk=2)
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=2))
        fresh = self.make_order(milk=1)
        cancelled, recovered = services.expire_pending_orders(timeout_minutes=30)
        self.assertEqual((cancelled, recovered), (1, 0))
        old.refresh_from_db(); fresh.refresh_from_db(); self.milk.refresh_from_db()
        self.assertEqual(old.status, "cancelled")
        self.assertEqual(fresh.status, "pending_payment")
        self.assertEqual(self.milk.stock, 4)  # ۵ - ۱ (سفارش تازه)

    def test_expire_recovers_payment_with_lost_callback(self):
        order = self.make_order()
        Payment.objects.filter(order=order).update(authority="AUTH1")
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(hours=1))
        with mock.patch("orders.services.zarinpal.verify_payment", return_value=(zarinpal.VERIFY_SUCCESS, "REF")):
            cancelled, recovered = services.expire_pending_orders(timeout_minutes=30)
        self.assertEqual((cancelled, recovered), (0, 1))
        order.refresh_from_db()
        self.assertEqual(order.status, "processing")

    def test_expire_skips_when_gateway_unreachable(self):
        order = self.make_order()
        Payment.objects.filter(order=order).update(authority="AUTH1")
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(hours=1))
        with mock.patch("orders.services.zarinpal.verify_payment", return_value=(zarinpal.VERIFY_ERROR, "x")):
            cancelled, recovered = services.expire_pending_orders(timeout_minutes=30)
        self.assertEqual((cancelled, recovered), (0, 0))
        order.refresh_from_db()
        self.assertEqual(order.status, "pending_payment")  # تا روشن شدن وضعیت، لغو نمی‌شود

    def test_late_payment_revives_cancelled_order_when_stock_available(self):
        order = self.make_order(milk=2)
        services.cancel_order(order)
        self.assertEqual(services.mark_order_paid(order, "REF"), "paid")
        order.refresh_from_db(); self.milk.refresh_from_db()
        self.assertEqual(order.status, "processing")
        self.assertEqual(self.milk.stock, 3)

    def test_late_payment_without_stock_is_flagged(self):
        order = self.make_order(milk=2)
        services.cancel_order(order)
        Product.objects.filter(pk=self.milk.pk).update(stock=0)
        self.assertEqual(services.mark_order_paid(order, "REF"), "paid_but_cancelled")
        order.refresh_from_db()
        self.assertEqual(order.status, "cancelled")
        self.assertEqual(order.payment.status, "success")  # پرداخت ثبت شده تا ادمین بتواند وجه را برگرداند

    def test_management_commands_run(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("expire_pending_orders", stdout=out)
        call_command("reconcile_payments", stdout=out)
        self.assertIn("لغو شده", out.getvalue())


class OrderAccessTests(BaseShopTest):
    def test_user_cannot_view_others_order(self):
        order = self.make_order()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("orders:order_detail", args=[order.id])).status_code, 404)

    def test_order_detail_shows_pay_and_cancel_for_pending(self):
        order = self.make_order()
        html = self.client.get(reverse("orders:order_detail", args=[order.id])).content.decode()
        self.assertIn(reverse("orders:payment", args=[order.id]), html)
        self.assertIn(reverse("orders:order_cancel", args=[order.id]), html)


class AdminOrderTests(BaseShopTest):
    def test_non_staff_redirected(self):
        self.assertEqual(self.client.get(reverse("orders:admin_order_list")).status_code, 302)

    def test_staff_search_and_status_filter(self):
        order = self.make_order()
        self.client.force_login(self.staff)
        by_id = self.client.get(reverse("orders:admin_order_list"), {"q": str(order.id)})
        self.assertEqual(len(by_id.context["orders"]), 1)
        by_phone = self.client.get(reverse("orders:admin_order_list"), {"q": "09120000100"})
        self.assertEqual(len(by_phone.context["orders"]), 1)
        none = self.client.get(reverse("orders:admin_order_list"), {"q": "zzz"})
        self.assertEqual(len(none.context["orders"]), 0)
        shipped = self.client.get(reverse("orders:admin_order_list"), {"status": "shipped"})
        self.assertEqual(len(shipped.context["orders"]), 0)

    def test_admin_cancel_restores_stock(self):
        order = self.make_order(milk=2)
        self.client.force_login(self.staff)
        self.client.post(reverse("orders:admin_order_detail", args=[order.id]), {"status": "cancelled"})
        order.refresh_from_db(); self.milk.refresh_from_db()
        self.assertEqual(order.status, "cancelled")
        self.assertEqual(self.milk.stock, 5)

    def test_admin_cannot_reopen_cancelled_order(self):
        order = self.make_order()
        services.cancel_order(order)
        self.client.force_login(self.staff)
        self.client.post(reverse("orders:admin_order_detail", args=[order.id]), {"status": "processing"})
        order.refresh_from_db()
        self.assertEqual(order.status, "cancelled")

    def test_admin_normal_status_change(self):
        order = self.make_order()
        services.mark_order_paid(order, "R")
        self.client.force_login(self.staff)
        self.client.post(reverse("orders:admin_order_detail", args=[order.id]), {"status": "shipped"})
        order.refresh_from_db()
        self.assertEqual(order.status, "shipped")
