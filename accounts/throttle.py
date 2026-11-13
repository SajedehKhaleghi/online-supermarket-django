"""محدودسازی ساده‌ی نرخ درخواست بر پایه‌ی cache جنگو (برای جلوگیری از بمباران پیامکی و حدس OTP).

نکته: با LocMemCache (پیش‌فرض) شمارنده برای هر پردازش جداست. در production با چند worker،
یک cache مشترک (Redis / Memcached / DatabaseCache) در CACHES تنظیم کنید تا سقف‌ها دقیق اعمال شوند.
"""
from django.core.cache import cache


def client_ip(request):
    # پشت reverse proxy باید پروکسی X-Forwarded-For را «بازنویسی» کند، نه اینکه از کلاینت بپذیرد.
    # برای سادگی و جلوگیری از جعل، فقط REMOTE_ADDR استفاده می‌شود.
    return request.META.get("REMOTE_ADDR", "unknown")


def is_limited(scope, ident, limit, window_seconds):
    """بدون شمردن، فقط بررسی می‌کند که سقف پر شده یا نه."""
    return cache.get(f"throttle:{scope}:{ident}", 0) >= limit


def reset(scope, ident):
    cache.delete(f"throttle:{scope}:{ident}")


def hit(scope, ident, window_seconds):
    """یک رخداد ثبت می‌کند (پنجره از اولین رخداد شروع می‌شود)."""
    key = f"throttle:{scope}:{ident}"
    if cache.add(key, 1, window_seconds):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # کلید بین add و incr منقضی شد
        cache.set(key, 1, window_seconds)
        return 1
