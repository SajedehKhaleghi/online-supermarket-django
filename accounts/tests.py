from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import OTPCode, User
from .views import purge_unverified_users

REGISTER_DATA = {
    "username": "ali", "phone_number": "09121234567",
    "password1": "S0me-Strong-Pass!", "password2": "S0me-Strong-Pass!",
}


class OTPModelTests(TestCase):
    def test_code_is_six_digits_and_stored_hashed(self):
        otp, plain = OTPCode.generate_code("09121234567")
        self.assertEqual(len(plain), 6)
        self.assertTrue(plain.isdigit())
        self.assertNotEqual(otp.code, plain)
        self.assertTrue(otp.check_code(plain))
        self.assertFalse(otp.check_code("000000" if plain != "000000" else "111111"))

    def test_expiry(self):
        otp, _ = OTPCode.generate_code("09121234567")
        self.assertTrue(otp.is_valid())
        OTPCode.objects.filter(pk=otp.pk).update(created_at=timezone.now() - timedelta(minutes=3))
        otp.refresh_from_db()
        self.assertFalse(otp.is_valid())


@mock.patch("accounts.views.sms.send_otp")
class RegistrationFlowTests(TestCase):
    def _register(self, send):
        response = self.client.post(reverse("accounts:register"), REGISTER_DATA)
        code = send.call_args[0][1] if send.called else None
        return response, code

    def test_register_creates_inactive_user_and_sends_otp(self, send):
        response, code = self._register(send)
        self.assertRedirects(response, reverse("accounts:verify_otp"))
        user = User.objects.get(username="ali")
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_phone_verified)
        self.assertEqual(len(code), 6)

    def test_unverified_user_cannot_log_in(self, send):
        self._register(send)
        ok = self.client.login(username="ali", password="S0me-Strong-Pass!")
        self.assertFalse(ok)

    def test_correct_code_activates_and_logs_in(self, send):
        _, code = self._register(send)
        response = self.client.post(reverse("accounts:verify_otp"), {"code": code})
        self.assertRedirects(response, reverse("products:home"))
        user = User.objects.get(username="ali")
        self.assertTrue(user.is_active and user.is_phone_verified)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)

    def test_wrong_code_is_rejected_and_counted(self, send):
        _, code = self._register(send)
        wrong = "000000" if code != "000000" else "111111"
        self.client.post(reverse("accounts:verify_otp"), {"code": wrong})
        self.assertEqual(OTPCode.objects.get().attempts, 1)
        self.assertFalse(User.objects.get(username="ali").is_active)

    def test_code_locked_after_max_attempts(self, send):
        _, code = self._register(send)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.client.post(reverse("accounts:verify_otp"), {"code": wrong})
        # حتی کد درست هم دیگر پذیرفته نمی‌شود
        self.client.post(reverse("accounts:verify_otp"), {"code": code})
        self.assertFalse(User.objects.get(username="ali").is_active)

    def test_expired_code_rejected(self, send):
        _, code = self._register(send)
        OTPCode.objects.update(created_at=timezone.now() - timedelta(minutes=5))
        self.client.post(reverse("accounts:verify_otp"), {"code": code})
        self.assertFalse(User.objects.get(username="ali").is_active)

    def test_resend_respects_cooldown(self, send):
        self._register(send)
        self.assertEqual(send.call_count, 1)
        self.client.post(reverse("accounts:resend_otp"))
        self.assertEqual(send.call_count, 1)  # هنوز در بازه‌ی cooldown
        OTPCode.objects.update(created_at=timezone.now() - timedelta(seconds=120))
        self.client.post(reverse("accounts:resend_otp"))
        self.assertEqual(send.call_count, 2)

    def test_resend_requires_post(self, send):
        self._register(send)
        self.assertEqual(self.client.get(reverse("accounts:resend_otp")).status_code, 405)

    def test_stale_unverified_users_are_purged(self, send):
        self._register(send)
        User.objects.update(date_joined=timezone.now() - timedelta(hours=2))
        purge_unverified_users()
        self.assertFalse(User.objects.filter(username="ali").exists())

    def test_purge_never_touches_staff_or_verified(self, send):
        User.objects.create_user("staff", password="x", phone_number="09120000001", is_staff=True, is_active=False)
        User.objects.create_user("ok", password="x", phone_number="09120000002", is_phone_verified=True, is_active=False)
        User.objects.update(date_joined=timezone.now() - timedelta(days=3))
        purge_unverified_users()
        self.assertEqual(User.objects.count(), 2)

    def test_invalid_phone_rejected(self, send):
        data = dict(REGISTER_DATA, phone_number="12345")
        response = self.client.post(reverse("accounts:register"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())


class LogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", password="pw-12345-xx", phone_number="09120000009")

    def test_logout_get_not_allowed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)

    def test_logout_post_keeps_compare_list(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["compare_list"] = [1, 2]
        session.save()
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.session["compare_list"], [1, 2])


class SMSBackendTests(TestCase):
    @override_settings(SMS_BACKEND="kavenegar", KAVENEGAR_API_KEY="")
    def test_kavenegar_without_key_raises(self):
        from . import sms
        with self.assertRaises(sms.SMSError):
            sms.send_otp("09121234567", "123456")

    @override_settings(SMS_BACKEND="kavenegar", KAVENEGAR_API_KEY="k", KAVENEGAR_OTP_TEMPLATE="verify")
    def test_kavenegar_calls_api(self):
        from . import sms
        with mock.patch("accounts.sms.requests.get") as get:
            sms.send_otp("09121234567", "123456")
        self.assertIn("/verify/lookup.json", get.call_args[0][0])
        self.assertEqual(get.call_args[1]["params"]["token"], "123456")
