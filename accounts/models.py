import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """کاربر سفارشی سایت با شماره موبایل به‌عنوان کلید احراز هویت پیامکی"""
    phone_number = models.CharField(max_length=11, unique=True, verbose_name="شماره موبایل")
    address = models.CharField(max_length=255, blank=True, verbose_name="آدرس")
    is_phone_verified = models.BooleanField(default=False, verbose_name="احراز هویت شده")

    # بدون این، createsuperuser دومی با phone_number خالی به UNIQUE می‌خورد
    REQUIRED_FIELDS = ["email", "phone_number"]

    def __str__(self):
        return f"{self.username} ({self.phone_number})"

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"


def _hash_code(phone_number, code):
    """کد OTP به‌صورت HMAC ذخیره می‌شود تا در دیتابیس/ادمین به‌صورت متن ساده دیده نشود."""
    message = f"{phone_number}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


class OTPCode(models.Model):
    """کد یک‌بارمصرف پیامکی برای احراز هویت هنگام ثبت‌نام"""
    phone_number = models.CharField(max_length=11, verbose_name="شماره موبایل", db_index=True)
    code = models.CharField(max_length=64, verbose_name="هش کد تایید")
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name="تعداد تلاش اشتباه")

    class Meta:
        verbose_name = "کد تایید پیامکی"
        verbose_name_plural = "کدهای تایید پیامکی"

    @classmethod
    def generate_code(cls, phone_number):
        """یک کد ۶ رقمی امن می‌سازد. خروجی: (شیء OTPCode, کد خام برای ارسال پیامک)"""
        plain = f"{secrets.randbelow(900000) + 100000}"
        otp = cls.objects.create(phone_number=phone_number, code=_hash_code(phone_number, plain))
        return otp, plain

    def check_code(self, plain):
        return hmac.compare_digest(self.code, _hash_code(self.phone_number, plain))

    @classmethod
    def purge_old(cls, days=1):
        """کدهای قدیمی (منقضی‌شده/مصرف‌شده) بی‌دلیل در دیتابیس نمی‌مانند."""
        return cls.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()

    @property
    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    @property
    def is_locked(self):
        return self.attempts >= settings.OTP_MAX_ATTEMPTS

    def is_valid(self):
        return (not self.is_used) and (not self.is_expired) and (not self.is_locked)

    def __str__(self):
        return f"{self.phone_number} ({self.created_at:%Y-%m-%d %H:%M})"
