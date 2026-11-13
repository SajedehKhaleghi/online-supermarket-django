"""تست‌های رگرسیون برای عیب‌هایی که در بازبینی کد پیدا و رفع شدند."""
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from accounts.forms import RegisterForm, OTPVerifyForm
from accounts.models import OTPCode, User
from orders import services, zarinpal
from orders.models import Cart
from products.forms import ProductForm
from products.models import Category, Product


class ZarinpalPayloadTests(TestCase):
    class Resp:
        def __init__(self, payload=None, boom=False):
            self.payload, self.boom = payload, boom

        def json(self):
            if self.boom:
                raise ValueError("not json")
            return self.payload

    def test_error_payload_with_empty_list_data_raises_zarinpal_error(self):
        resp = self.Resp({"data": [], "errors": {"code": -9}})
        with mock.patch("orders.zarinpal.requests.post", return_value=resp):
            with self.assertRaises(zarinpal.ZarinpalError):
                zarinpal.request_payment(1000, "d", "http://x/")

    def test_non_json_response_raises_zarinpal_error(self):
        with mock.patch("orders.zarinpal.requests.post", return_value=self.Resp(boom=True)):
            with self.assertRaises(zarinpal.ZarinpalError):
                zarinpal.request_payment(1000, "d", "http://x/")

    def test_verify_with_list_data_is_failed_not_crash(self):
        resp = self.Resp({"data": [], "errors": {"code": -50}})
        with mock.patch("orders.zarinpal.requests.post", return_value=resp):
            status, _ = zarinpal.verify_payment(1000, "A")
        self.assertEqual(status, zarinpal.VERIFY_FAILED)


class ProductRegressionTests(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(name="c")

    def test_discount_over_100_rejected_by_form(self):
        form = ProductForm({"category": self.cat.id, "name": "x", "description": "d", "price": 100,
                            "discount_percent": 150, "unit": "piece", "stock": 1, "is_active": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("discount_percent", form.errors)

    def test_final_price_never_negative(self):
        p = Product(category=self.cat, name="p", description="d", price=1000, discount_percent=150)
        self.assertEqual(p.final_price, 0)

    def test_non_ascii_digit_price_filter_does_not_crash(self):
        for value in ["²", "٣", "99999999999999999999999", "-5", "abc"]:
            r = self.client.get("/products/", {"min_price": value, "max_price": value})
            self.assertEqual(r.status_code, 200, value)

    def test_symbol_only_names_get_valid_unique_slugs(self):
        c1, c2 = Category.objects.create(name="!!!"), Category.objects.create(name="???")
        self.assertTrue(c1.slug and c2.slug and c1.slug != c2.slug)
        self.assertTrue(c1.get_absolute_url())
        p = Product.objects.create(category=self.cat, name="@@", description="d", price=1)
        self.assertTrue(p.slug)

    def test_admin_create_with_invalid_formset_does_not_save_product(self):
        staff = User.objects.create_user("s", password="x", phone_number="09120000002", is_staff=True)
        c = Client(); c.force_login(staff)
        data = {"category": self.cat.id, "name": "prod", "description": "d", "price": 10, "discount_percent": 0,
                "unit": "piece", "stock": 1, "is_active": "on",
                "features-TOTAL_FORMS": 1, "features-INITIAL_FORMS": 0,
                "features-MIN_NUM_FORMS": 0, "features-MAX_NUM_FORMS": 1000,
                "features-0-key": "only-key", "features-0-value": ""}
        r = c.post(reverse("products:admin_product_create"), data)
        self.assertEqual(r.status_code, 200)  # فرم با خطا دوباره نمایش داده می‌شود
        self.assertFalse(Product.objects.filter(name="prod").exists())


class AccountRegressionTests(TestCase):
    def test_second_superuser_with_phone_is_possible(self):
        User.objects.create_superuser("a1", "a@x.com", "x", phone_number="09120000010")
        User.objects.create_superuser("a2", "b@x.com", "x", phone_number="09120000011")

    def test_persian_digits_accepted_for_phone_and_otp(self):
        pw = "Str0ng!pass99"
        form = RegisterForm({"username": "n", "phone_number": "۰۹۱۲۳۴۵۶۷۸۹", "password1": pw, "password2": pw})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_number"], "09123456789")
        otp = OTPVerifyForm({"code": "۱۲۳۴۵۶"})
        self.assertTrue(otp.is_valid())
        self.assertEqual(otp.cleaned_data["code"], "123456")

    def test_error_messages_use_bootstrap_danger_class(self):
        from django.contrib.messages import constants
        from django.contrib.messages.utils import get_level_tags
        self.assertEqual(get_level_tags()[constants.ERROR], "danger")


class AdminOrderRegressionTests(TestCase):
    def test_admin_cannot_ship_unpaid_order(self):
        cat = Category.objects.create(name="c")
        prod = Product.objects.create(category=cat, name="p", description="d", price=1000, stock=5)
        user = User.objects.create_user("u", password="x", phone_number="09120000001")
        staff = User.objects.create_user("s", password="x", phone_number="09120000002", is_staff=True)
        Cart.objects.get(user=user).items.create(product=prod, quantity=1)
        order = services.create_order_from_cart(user, "a", "t")
        c = Client(); c.force_login(staff)
        c.post(reverse("orders:admin_order_detail", args=[order.id]), {"status": "delivered"})
        order.refresh_from_db()
        self.assertEqual(order.status, "pending_payment")


# ---------------------------------------------------------------------------
# دور دوم: تاریخچه‌ی Authority، PROTECT، throttle ثبت‌نام، فایل‌های محلی
# ---------------------------------------------------------------------------
from django.core.cache import cache
from django.db.models import ProtectedError
from django.test import override_settings
from django.template.loader import render_to_string


LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class PaymentAuthorityHistoryTests(TestCase):
    def setUp(self):
        cat = Category.objects.create(name="c")
        self.prod = Product.objects.create(category=cat, name="p", description="d", price=1000, stock=10)
        self.user = User.objects.create_user("u", password="x", phone_number="09120000001")
        Cart.objects.get(user=self.user).items.create(product=self.prod, quantity=1)
        self.order = services.create_order_from_cart(self.user, "a", "t")
        self.client = Client(); self.client.force_login(self.user)

    def _start_twice(self):
        seq = iter(["A1", "A2"])
        with mock.patch("orders.zarinpal.request_payment",
                        side_effect=lambda **k: (n := next(seq), "http://gw/" + n)):
            self.client.get(reverse("orders:payment", args=[self.order.id]))
            self.client.get(reverse("orders:payment", args=[self.order.id]))

    def test_payment_on_older_authority_is_accepted(self):
        self._start_twice()
        self.order.payment.refresh_from_db()
        self.assertEqual(self.order.payment.authority, "A2")
        self.assertCountEqual(self.order.payment.known_authorities(), ["A1", "A2"])
        with mock.patch("orders.zarinpal.verify_payment", return_value=("success", "REF")) as v:
            self.client.get(reverse("orders:payment_verify", args=[self.order.id]),
                            {"Authority": "A1", "Status": "OK"})
        self.assertEqual(v.call_args.kwargs["authority"], "A1")   # با همان Authority قدیمی وریفای می‌شود
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "processing")

    def test_foreign_authority_still_rejected(self):
        self._start_twice()
        with mock.patch("orders.zarinpal.verify_payment") as v:
            self.client.get(reverse("orders:payment_verify", args=[self.order.id]),
                            {"Authority": "OTHER-ORDER", "Status": "OK"})
        v.assert_not_called()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending_payment")

    def test_cancel_on_old_authority_does_not_fail_current_payment(self):
        self._start_twice()
        self.client.get(reverse("orders:payment_verify", args=[self.order.id]),
                        {"Authority": "A1", "Status": "NOK"})
        self.order.payment.refresh_from_db()
        self.assertEqual(self.order.payment.status, "pending")

    def test_reconcile_finds_payment_made_on_old_authority(self):
        self._start_twice()
        def fake_verify(amount, authority):
            return ("success", "REF") if authority == "A1" else ("failed", "no")
        with mock.patch("orders.services.zarinpal.verify_payment", side_effect=fake_verify):
            status = services.reconcile_payment(self.order.payment)
        self.assertEqual(status, zarinpal.VERIFY_SUCCESS)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "processing")

    def test_reconcile_network_error_on_any_authority_keeps_order_pending(self):
        self._start_twice()
        def fake_verify(amount, authority):
            return ("error", "net") if authority == "A2" else ("failed", "no")
        with mock.patch("orders.services.zarinpal.verify_payment", side_effect=fake_verify):
            self.assertEqual(services.reconcile_payment(self.order.payment), zarinpal.VERIFY_ERROR)


class OrderUserProtectTests(TestCase):
    def test_deleting_user_with_orders_is_blocked(self):
        cat = Category.objects.create(name="c")
        prod = Product.objects.create(category=cat, name="p", description="d", price=1000, stock=5)
        user = User.objects.create_user("u", password="x", phone_number="09120000001")
        Cart.objects.get(user=user).items.create(product=prod, quantity=1)
        services.create_order_from_cart(user, "a", "t")
        with self.assertRaises(ProtectedError):
            user.delete()


@override_settings(CACHES=LOCMEM, OTP_SMS_LIMIT_PER_PHONE_PER_HOUR=2, REGISTER_LIMIT_PER_IP_PER_HOUR=3)
class RegistrationAbuseTests(TestCase):
    PW = "Str0ng!pass99"

    def setUp(self):
        cache.clear()

    def _register(self, username, phone):
        return self.client.post(reverse("accounts:register"), {
            "username": username, "phone_number": phone, "password1": self.PW, "password2": self.PW})

    @mock.patch("accounts.views.sms.send_otp")
    def test_pending_registration_does_not_lock_the_real_owner(self, send):
        self._register("attacker", "09123456789")          # شماره‌ی قربانی با ثبت‌نام الکی گرفته شد
        r = Client().post(reverse("accounts:register"), {  # مالک واقعی همان شماره
            "username": "victim", "phone_number": "09123456789",
            "password1": self.PW, "password2": self.PW})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(username="attacker").exists())
        self.assertTrue(User.objects.filter(username="victim").exists())

    @mock.patch("accounts.views.sms.send_otp")
    def test_sms_to_one_phone_is_capped(self, send):
        for i in range(5):
            self._register(f"u{i}", "09123456789")
        self.assertEqual(send.call_count, 2)   # سقف ۲ پیامک در ساعت برای این شماره

    @mock.patch("accounts.views.sms.send_otp")
    def test_register_is_capped_per_ip(self, send):
        codes = [self._register(f"x{i}", f"0912345678{i}").status_code for i in range(5)]
        self.assertEqual(codes[:3], [302, 302, 302])
        self.assertEqual(codes[3:], [429, 429])

    @mock.patch("accounts.views.sms.send_otp")
    def test_verified_or_staff_accounts_are_never_released(self, send):
        User.objects.create_user("real", password="x", phone_number="09123456789",
                                 is_active=True, is_phone_verified=True)
        r = self._register("dup", "09123456789")
        self.assertEqual(r.status_code, 200)   # فرم با خطا
        self.assertTrue(User.objects.filter(username="real").exists())


class LocalAssetsTests(TestCase):
    def test_base_template_has_no_external_hosts(self):
        html = render_to_string("base.html", {"user": None, "messages": []})
        self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertNotIn("placehold.co", html)
        self.assertIn("vendor/bootstrap/bootstrap.rtl.min.css", html)

    def test_no_template_references_external_placeholder(self):
        import pathlib
        from django.conf import settings
        for f in (pathlib.Path(settings.BASE_DIR) / "templates").rglob("*.html"):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("placehold.co", text, f)
            self.assertNotIn("cdn.jsdelivr", text, f)

    def test_vendor_files_exist(self):
        import pathlib
        from django.conf import settings
        for rel in ["vendor/bootstrap/bootstrap.rtl.min.css", "vendor/bootstrap/bootstrap.bundle.min.js",
                    "vendor/vazirmatn/vazirmatn.css", "vendor/vazirmatn/Vazirmatn-Variable.woff2", "img/no-image.svg"]:
            self.assertTrue((pathlib.Path(settings.BASE_DIR) / "static" / rel).is_file(), rel)


# ---------------------------------------------------------------------------
# دور سوم
# ---------------------------------------------------------------------------
import pathlib
import tempfile
from datetime import timedelta

from django.utils import timezone

from orders.models import Order


class PaidOrderProtectionTests(TestCase):
    def setUp(self):
        cat = Category.objects.create(name="c")
        self.prod = Product.objects.create(category=cat, name="p", description="d", price=1000, stock=5)
        self.user = User.objects.create_user("u", password="x", phone_number="09120000001")
        self.staff = User.objects.create_user("s", password="x", phone_number="09120000002", is_staff=True)
        Cart.objects.get(user=self.user).items.create(product=self.prod, quantity=2)
        self.order = services.create_order_from_cart(self.user, "a", "t")
        services.mark_order_paid(self.order, "REF")
        self.admin = Client(); self.admin.force_login(self.staff)

    def test_admin_cannot_revert_paid_order_to_pending(self):
        self.admin.post(reverse("orders:admin_order_detail", args=[self.order.id]), {"status": "pending_payment"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "processing")

    def test_expiry_never_cancels_a_paid_order_even_if_status_was_forced(self):
        Order.objects.filter(pk=self.order.pk).update(
            status="pending_payment", created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(services.expire_pending_orders(timeout_minutes=30), (0, 0))
        self.order.refresh_from_db(); self.prod.refresh_from_db()
        self.assertEqual(self.order.status, "pending_payment")
        self.assertEqual(self.prod.stock, 3)   # موجودی آزاد نشد

    def test_admin_cancelling_paid_order_warns_about_refund(self):
        r = self.admin.post(reverse("orders:admin_order_detail", args=[self.order.id]),
                            {"status": "cancelled"}, follow=True)
        text = " ".join(str(m) for m in r.context["messages"])
        self.assertIn("برگردانید", text)


@override_settings(CACHES=LOCMEM, LOGIN_FAILURE_LIMIT_PER_USERNAME=3, LOGIN_FAILURE_LIMIT_PER_IP=100)
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user("v", password="correct-horse-1", phone_number="09120000003")

    def _login(self, pw, client=None):
        return (client or self.client).post(reverse("accounts:login"), {"username": "v", "password": pw})

    def test_wrong_passwords_are_capped_then_even_correct_one_is_blocked(self):
        for i in range(3):
            self.assertEqual(self._login(f"bad{i}").status_code, 200)
        self.assertEqual(self._login("bad4").status_code, 429)
        self.assertEqual(self._login("correct-horse-1").status_code, 429)

    def test_successful_login_resets_counter(self):
        for i in range(2):
            self._login(f"bad{i}")
        self.assertEqual(self._login("correct-horse-1").status_code, 302)
        self.client.logout()
        for i in range(2):
            self.assertEqual(self._login(f"bad{i}").status_code, 200)


class DotenvParsingTests(TestCase):
    def _parse(self, text):
        import os
        from supermarket_shop import settings as st
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / ".env"; f.write_text(text, encoding="utf-8")
            keys = [l.split("=")[0].replace("export ", "").strip() for l in text.splitlines() if "=" in l]
            saved = {k: os.environ.pop(k, None) for k in keys}
            try:
                st._load_dotenv(f)
                return {k: os.environ.get(k) for k in keys}
            finally:
                for k in keys:
                    os.environ.pop(k, None)
                    if saved[k] is not None:
                        os.environ[k] = saved[k]

    def test_inline_comments_and_quotes(self):
        got = self._parse('ZZ_A=abc # comment\nZZ_B="a b" # c\nZZ_C=\'x#y\'\nZZ_D=pa#ss\nexport ZZ_E=1\n# ZZ_F=no\n')
        self.assertEqual(got["ZZ_A"], "abc")
        self.assertEqual(got["ZZ_B"], "a b")
        self.assertEqual(got["ZZ_C"], "x#y")
        self.assertEqual(got["ZZ_D"], "pa#ss")     # # بدون فاصله‌ی قبلش کامنت نیست
        self.assertEqual(got["ZZ_E"], "1")


class MiscRegressionTests(TestCase):
    def test_old_otp_codes_are_purged(self):
        old, _ = OTPCode.generate_code("09120000009")
        OTPCode.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
        fresh, _ = OTPCode.generate_code("09120000008")
        OTPCode.purge_old()
        self.assertFalse(OTPCode.objects.filter(pk=old.pk).exists())
        self.assertTrue(OTPCode.objects.filter(pk=fresh.pk).exists())

    def test_dashboard_shows_only_recent_orders_with_link(self):
        cat = Category.objects.create(name="c")
        prod = Product.objects.create(category=cat, name="p", description="d", price=10, stock=100)
        user = User.objects.create_user("u", password="x", phone_number="09120000001")
        for _ in range(7):
            Cart.objects.get(user=user).items.create(product=prod, quantity=1)
            services.create_order_from_cart(user, "a", "t")
        c = Client(); c.force_login(user)
        r = c.get(reverse("accounts:dashboard"))
        self.assertEqual(len(r.context["orders"]), 5)
        self.assertContains(r, reverse("orders:order_list"))
