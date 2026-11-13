"""
کلاینت ساده برای اتصال به درگاه پرداخت زرین‌پال (Zarinpal).
مستندات: https://docs.zarinpal.com/paymentGateway/

برای استفاده واقعی:
1. در settings.py مقدار ZARINPAL_MERCHANT_ID را با مرچنت‌کد واقعی خود جایگزین کنید.
2. ZARINPAL_SANDBOX را روی False بگذارید (پس از تایید درگاه توسط زرین‌پال).
3. سایت باید روی دامنه‌ی https اجرا شود (callback از روی درخواست فعلی ساخته می‌شود).

در محیط sandbox، زرین‌پال تراکنش را همیشه با کد ۱۰۰ موفق برمی‌گرداند و پول واقعی
جابه‌جا نمی‌شود، بنابراین برای تست کامل است.
"""
import requests
from django.conf import settings

SANDBOX_BASE = "https://sandbox.zarinpal.com/pg/v4/payment"
PRODUCTION_BASE = "https://payment.zarinpal.com/pg/v4/payment"
SANDBOX_STARTPAY = "https://sandbox.zarinpal.com/pg/StartPay/"
PRODUCTION_STARTPAY = "https://payment.zarinpal.com/pg/StartPay/"


def _base_url():
    return SANDBOX_BASE if settings.ZARINPAL_SANDBOX else PRODUCTION_BASE


def _startpay_url():
    return SANDBOX_STARTPAY if settings.ZARINPAL_SANDBOX else PRODUCTION_STARTPAY


class ZarinpalError(Exception):
    pass


def request_payment(amount_toman, description, callback_url, mobile=None, email=None):
    """
    مرحله اول: درخواست ایجاد تراکنش.
    amount_toman: مبلغ به تومان (زرین‌پال از نسخه v4 به بعد تومان می‌پذیرد؛ ریال = تومان * 10)
    خروجی: authority (کد پیگیری) برای هدایت کاربر به درگاه.
    """
    payload = {
        "merchant_id": settings.ZARINPAL_MERCHANT_ID,
        "amount": amount_toman * 10,  # تبدیل به ریال طبق الزام API
        "description": description,
        "callback_url": callback_url,
    }
    metadata = {}
    if mobile:
        metadata["mobile"] = mobile
    if email:
        metadata["email"] = email
    if metadata:
        payload["metadata"] = metadata

    try:
        response = requests.post(f"{_base_url()}/request.json", json=payload, timeout=10)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ZarinpalError(f"خطا در اتصال به درگاه پرداخت: {exc}")

    # زرین‌پال در حالت خطا «data» را به‌صورت لیست خالی برمی‌گرداند، نه دیکشنری
    if not isinstance(data, dict):
        raise ZarinpalError("پاسخ نامعتبر از درگاه پرداخت.")
    body = data.get("data")
    if isinstance(body, dict) and body.get("code") == 100 and body.get("authority"):
        authority = body["authority"]
        return authority, f"{_startpay_url()}{authority}"

    raise ZarinpalError(f"خطا در ایجاد تراکنش زرین‌پال: {data.get('errors')}")


VERIFY_SUCCESS = "success"
VERIFY_FAILED = "failed"   # درگاه صراحتاً پرداخت را تایید نکرد
VERIFY_ERROR = "error"     # خطای شبکه/نامشخص؛ نتیجه‌ی نهایی نیست و باید بعداً دوباره بررسی شود


def verify_payment(amount_toman, authority):
    """
    مرحله دوم: پس از بازگشت کاربر از درگاه، صحت پرداخت را بررسی می‌کند.
    خروجی: (status, detail) که status یکی از VERIFY_SUCCESS / VERIFY_FAILED / VERIFY_ERROR است
    و detail برای موفقیت ref_id و در غیر این صورت متن خطاست.
    """
    payload = {
        "merchant_id": settings.ZARINPAL_MERCHANT_ID,
        "amount": amount_toman * 10,
        "authority": authority,
    }
    try:
        response = requests.post(f"{_base_url()}/verify.json", json=payload, timeout=10)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        return VERIFY_ERROR, f"خطا در اتصال به درگاه پرداخت: {exc}"

    if not isinstance(data, dict):
        return VERIFY_ERROR, "پاسخ نامعتبر از درگاه پرداخت."
    body = data.get("data")
    code = body.get("code") if isinstance(body, dict) else None
    if code in (100, 101):  # 101 یعنی این تراکنش قبلاً وریفای شده (idempotent)
        return VERIFY_SUCCESS, str(body.get("ref_id", ""))

    return VERIFY_FAILED, str(data.get("errors"))
