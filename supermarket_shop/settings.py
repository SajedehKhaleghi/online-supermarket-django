"""
تنظیمات پروژه‌ی سوپرمارکت آنلاین.

همه‌ی مقادیر حساس (SECRET_KEY، مرچنت‌کد، دامنه و ...) از متغیرهای محیطی یا فایل `.env`
خوانده می‌شوند. برای شروع، فایل `.env.example` را به `.env` کپی کنید.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# خواندن .env (بدون نیاز به پکیج اضافه)
# ---------------------------------------------------------------------------
def _parse_env_value(raw):
    """مقدار یک خط .env: مقدار داخل کوتیشن همان‌طور که هست؛ مقدار بدون کوتیشن بدون کامنت هم‌خط (« # ...»)."""
    value = raw.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
    for i, ch in enumerate(value):
        if ch == "#" and (i == 0 or value[i - 1].isspace()):
            value = value[:i]
            break
    return value.strip()


def _load_dotenv(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), _parse_env_value(value))


_load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# امنیت
# ---------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # فقط برای توسعه‌ی محلی؛ در production حتماً DJANGO_SECRET_KEY را تنظیم کنید.
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "متغیر DJANGO_SECRET_KEY تنظیم نشده است. فایل .env.example را به .env کپی کنید."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True


# ---------------------------------------------------------------------------
# اپلیکیشن‌ها
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'products',
    'orders',
]

AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'supermarket_shop.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'products.context_processors.compare_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'supermarket_shop.wsgi.application'


# ---------------------------------------------------------------------------
# دیتابیس (پیش‌فرض SQLite؛ برای MySQL مقدار DB_ENGINE=mysql و `pip install mysqlclient`)
# ---------------------------------------------------------------------------
if env("DB_ENGINE", "sqlite") == "mysql":
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': env("DB_NAME", "dbtamrin"),
            'USER': env("DB_USER", "root"),
            'PASSWORD': env("DB_PASSWORD", ""),
            'HOST': env("DB_HOST", "localhost"),
            'PORT': env("DB_PORT", "3306"),
            'OPTIONS': {'charset': 'utf8mb4'},
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / env("SQLITE_NAME", "db.sqlite3"),
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# هش سریع فقط هنگام اجرای تست‌ها (تا تست‌ها کند نشوند)
import sys  # noqa: E402
if "test" in sys.argv[1:2]:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# cache: پیش‌فرض LocMem (برای شمارنده‌های محدودسازی نرخ). در تست‌ها خاموش است تا شمارنده‌ها بین
# تست‌ها نشت نکنند؛ تست‌های مخصوص throttle با override_settings یک cache محلی می‌گیرند.
CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.dummy.DummyCache"
            if "test" in sys.argv[1:2]
            else "django.core.cache.backends.locmem.LocMemCache"
        )
    }
}

LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# فایل‌های استاتیک و مدیا
# ---------------------------------------------------------------------------
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'   # خروجی `collectstatic` برای production
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Bootstrap کلاس alert-error ندارد؛ معادل آن alert-danger است
from django.contrib.messages import constants as _msg  # noqa: E402
MESSAGE_TAGS = {_msg.ERROR: 'danger'}

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'products:home'
LOGOUT_REDIRECT_URL = 'products:home'


# ---------------------------------------------------------------------------
# درگاه پرداخت زرین‌پال
# ---------------------------------------------------------------------------
ZARINPAL_MERCHANT_ID = env("ZARINPAL_MERCHANT_ID", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
# پیش‌فرض: sandbox فقط در DEBUG. در sandbox همه‌ی پرداخت‌ها «موفق» برمی‌گردند (پول واقعی جابه‌جا نمی‌شود)
ZARINPAL_SANDBOX = env_bool("ZARINPAL_SANDBOX", DEBUG)
if not DEBUG and ZARINPAL_SANDBOX:
    raise ImproperlyConfigured(
        "در production نباید ZARINPAL_SANDBOX فعال باشد؛ در sandbox سفارش‌ها بدون پرداخت واقعی تایید می‌شوند."
    )

# شبیه‌سازی پرداخت فقط در حالت DEBUG مجاز است و در production همیشه غیرفعال می‌شود.
ALLOW_PAYMENT_SIMULATION = DEBUG and env_bool("ALLOW_PAYMENT_SIMULATION", True)

# سفارش‌های پرداخت‌نشده بعد از این مدت (دقیقه) لغو و موجودی‌شان آزاد می‌شود
# (دستور: python manage.py expire_pending_orders — با cron اجرا شود)
# پرداخت‌های جدیدتر از این مدت (دقیقه) توسط reconcile_payments استعلام می‌شوند
PAYMENT_RECONCILE_WINDOW_MINUTES = int(env("PAYMENT_RECONCILE_WINDOW_MINUTES", "120"))

PENDING_ORDER_TIMEOUT_MINUTES = int(env("PENDING_ORDER_TIMEOUT_MINUTES", "30"))


# ---------------------------------------------------------------------------
# پیامک (OTP)
# ---------------------------------------------------------------------------
# console  : کد در کنسول چاپ می‌شود (توسعه)
# kavenegar: ارسال واقعی با سرویس کاوه‌نگار (نیازمند KAVENEGAR_API_KEY و KAVENEGAR_OTP_TEMPLATE)
SMS_BACKEND = env("SMS_BACKEND", "console")
if not DEBUG and SMS_BACKEND == "console":
    import warnings
    warnings.warn("SMS_BACKEND=console در production: کد تایید به کاربر پیامک نمی‌شود و در لاگ چاپ می‌شود.")
KAVENEGAR_API_KEY = env("KAVENEGAR_API_KEY", "")
KAVENEGAR_OTP_TEMPLATE = env("KAVENEGAR_OTP_TEMPLATE", "verify")

# سقف نرخ (تعداد در ساعت) برای جلوگیری از بمباران پیامکی/سوءاستفاده
REGISTER_LIMIT_PER_IP_PER_HOUR = int(env("REGISTER_LIMIT_PER_IP_PER_HOUR", "10"))
OTP_SMS_LIMIT_PER_PHONE_PER_HOUR = int(env("OTP_SMS_LIMIT_PER_PHONE_PER_HOUR", "5"))
OTP_VERIFY_LIMIT_PER_IP_PER_HOUR = int(env("OTP_VERIFY_LIMIT_PER_IP_PER_HOUR", "30"))

# ورود: سقف «تلاش ناموفق» در هر ۱۵ دقیقه
LOGIN_FAILURE_LIMIT_PER_IP = int(env("LOGIN_FAILURE_LIMIT_PER_IP", "30"))
LOGIN_FAILURE_LIMIT_PER_USERNAME = int(env("LOGIN_FAILURE_LIMIT_PER_USERNAME", "10"))

OTP_EXPIRE_MINUTES = 2
OTP_MAX_ATTEMPTS = 5            # تعداد تلاش اشتباه مجاز برای هر کد
OTP_RESEND_COOLDOWN_SECONDS = 60
UNVERIFIED_USER_TTL_MINUTES = 30  # کاربرانی که OTP را تایید نکنند بعد از این مدت پاک می‌شوند


EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'