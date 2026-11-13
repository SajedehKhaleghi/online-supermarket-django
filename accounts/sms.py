"""ارسال پیامک با backend قابل تعویض (console برای توسعه، کاوه‌نگار برای production)."""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SMSError(Exception):
    pass


def send_otp(phone_number, code):
    backend = getattr(settings, "SMS_BACKEND", "console")
    if backend == "kavenegar":
        _send_kavenegar(phone_number, code)
    else:
        # فقط توسعه: کد در کنسول چاپ می‌شود.
        print(f"[SMS CONSOLE] کد تایید برای {phone_number}: {code}")


def _send_kavenegar(phone_number, code):
    if not settings.KAVENEGAR_API_KEY:
        raise SMSError("KAVENEGAR_API_KEY تنظیم نشده است.")
    url = f"https://api.kavenegar.com/v1/{settings.KAVENEGAR_API_KEY}/verify/lookup.json"
    try:
        response = requests.get(
            url,
            params={"receptor": phone_number, "token": code, "template": settings.KAVENEGAR_OTP_TEMPLATE},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # متن exception شامل URL (و کلید API) است؛ فقط نوع خطا لاگ می‌شود
        logger.error("ارسال پیامک ناموفق بود: %s", type(exc).__name__)
        raise SMSError("ارسال پیامک ناموفق بود") from None
