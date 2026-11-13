# فروشگاه آنلاین سوپرمارکت (Django)

فروشگاه اینترنتی سوپرمارکت با Django: ثبت‌نام با OTP پیامکی، کاتالوگ و جست‌وجو، نظرات و امتیاز،
**مقایسه‌ی محصولات**، سبد خرید، ثبت سفارش، پرداخت با **زرین‌پال** و پنل مدیریت محصول/سفارش.

## نصب و اجرا (توسعه)

```bash
python -m venv venv
source venv/bin/activate          # ویندوز: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # ویندوز: copy .env.example .env  (DJANGO_DEBUG=True برای توسعه)
python manage.py migrate
python manage.py seed_data --demo-admin   # داده‌ی نمونه + ادمین نمونه (admin / Admin@12345، فقط DEBUG)
python manage.py runserver
```

- سایت: http://127.0.0.1:8000/ — ادمین جنگو: `/admin/` — پنل فروشگاه: `/manage/products/`
- کد OTP در حالت توسعه (`SMS_BACKEND=console`) در **کنسول سرور** چاپ می‌شود.
- اجرای تست‌ها: `python manage.py test` (۱۱۷ تست؛ در GitHub Actions هم اجرا می‌شود)

## تنظیمات (`.env`)

| متغیر | توضیح |
|---|---|
| `DJANGO_DEBUG` | `True` فقط برای توسعه. در production حتماً `False` |
| `DJANGO_SECRET_KEY` | الزامی وقتی DEBUG خاموش است؛ بدون آن پروژه بالا نمی‌آید |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | دامنه‌ها |
| `ZARINPAL_MERCHANT_ID`, `ZARINPAL_SANDBOX` | درگاه پرداخت |
| `SMS_BACKEND` | `console` یا `kavenegar` (+ `KAVENEGAR_API_KEY`, `KAVENEGAR_OTP_TEMPLATE`) |
| `DB_ENGINE=mysql` + `DB_*` | استفاده از MySQL (نیازمند `pip install mysqlclient`) |
| `REGISTER_LIMIT_PER_IP_PER_HOUR`, `OTP_SMS_LIMIT_PER_PHONE_PER_HOUR`, `OTP_VERIFY_LIMIT_PER_IP_PER_HOUR` | سقف نرخ (در ساعت) برای ثبت‌نام، پیامک به هر شماره و تلاش تایید کد (پیش‌فرض ۱۰ / ۵ / ۳۰) |
| `LOGIN_FAILURE_LIMIT_PER_IP`, `LOGIN_FAILURE_LIMIT_PER_USERNAME` | سقف تلاش ناموفق ورود در ۱۵ دقیقه (پیش‌فرض ۳۰ / ۱۰) |
| `PAYMENT_RECONCILE_WINDOW_MINUTES` | پنجره‌ی استعلام پرداخت‌های معلق توسط `reconcile_payments` (پیش‌فرض ۱۲۰) |

## استقرار (production) — چک‌لیست

1. `DJANGO_DEBUG=False`، `DJANGO_SECRET_KEY` تصادفی، دامنه‌ها و HTTPS (کوکی‌ها و ریدایرکت HTTPS خودکار فعال می‌شوند).
2. `python manage.py collectstatic` و سرو `staticfiles/` و `media/` با وب‌سرور (Nginx).
3. `ZARINPAL_SANDBOX=False` و مرچنت‌کد واقعی. **شبیه‌سازی پرداخت در production همیشه غیرفعال است.**
4. دو کار زمان‌بندی‌شده (cron) هر ۵ تا ۱۵ دقیقه:
   ```
   python manage.py reconcile_payments     # پرداخت‌هایی که callback‌شان گم شده را از زرین‌پال استعلام می‌کند
   python manage.py expire_pending_orders  # سفارش‌های پرداخت‌نشده‌ی قدیمی را لغو و موجودی را آزاد می‌کند
   ```
5. `SMS_BACKEND=kavenegar` برای ارسال واقعی پیامک.
6. **cache مشترک:** محدودسازی نرخ از cache جنگو استفاده می‌کند. پیش‌فرض LocMem است (شمارنده‌ی هر worker جداست)؛
   با چند worker یک cache مشترک (Redis/Memcached) در `CACHES` تنظیم کنید. اگر پشت reverse proxy هستید و
   همه‌ی کاربران یک IP دیده می‌شوند، سقف IP را مناسب تنظیم کنید یا `REMOTE_ADDR` را درست پاس بدهید.
7. فایل‌های فرانت‌اند (Bootstrap RTL و فونت وزیرمتن) داخل `static/vendor/` هستند و از CDN لود نمی‌شوند؛
   پس `collectstatic` آن‌ها را هم برمی‌دارد. (Bootstrap 5.3.3 — MIT، Vazirmatn 33.0.3 — OFL؛ مجوزها کنار فایل‌ها هستند.)

## نکات طراحی

- **ثبت سفارش اتمیک است:** محصولات قفل می‌شوند، موجودی و فعال بودن بررسی و رزرو می‌شود؛ در هر خطا هیچ چیز ذخیره نمی‌شود.
- **موجودی رزرو می‌شود** هنگام ثبت سفارش و با لغو/انقضا برمی‌گردد؛ پرداخت دیرهنگام روی سفارش لغوشده در صورت وجود موجودی سفارش را احیا می‌کند، وگرنه برای بازگشت وجه علامت می‌خورد (لاگ هشدار).
- **تایید پرداخت سه‌حالته است** (موفق / ردشده / خطای شبکه)؛ خطای شبکه هرگز پرداخت را «ناموفق» ثبت نمی‌کند.
- **OTP:** تولید با `secrets`، ذخیره‌ی HMAC (نه متن ساده)، حداکثر ۵ تلاش، ارسال مجدد با cooldown، حساب تا تایید غیرفعال و کاربران تاییدنشده بعد از ۳۰ دقیقه پاک می‌شوند.
- همه‌ی عملیات تغییر وضعیت (سبد، مقایسه، خروج، لغو سفارش، پرداخت) فقط با **POST** + CSRF.
- مقایسه فقط بین محصولات هم‌دسته (حداکثر ۴) و با حفظ لیست پس از خروج.
- محصولی که در سفارش‌ها استفاده شده حذف نمی‌شود، غیرفعال می‌شود.
- **حذف کاربر دارای سفارش ممنوع است** (`on_delete=PROTECT`)؛ سابقه‌ی سفارش و پرداخت سند مالی است. برای مسدودکردن کاربر `is_active=False` بگذارید.
- **تاریخچه‌ی Authority:** هر بار که کاربر به درگاه می‌رود Authority جدید در `PaymentAuthority` ثبت می‌شود؛
  callback و `reconcile_payments` روی هر Authority معتبرِ همان سفارش کار می‌کنند، پس پرداخت از تب/کد قدیمی‌تر گم نمی‌شود.
- **ثبت‌نام ناتمام شماره را قفل نمی‌کند:** ثبت‌نام تاییدنشده با ثبت‌نام جدید همان شماره جایگزین می‌شود؛ ارسال پیامک و تلاش‌ها سقف نرخ دارند.
- تصویر پیش‌فرض محصول یک SVG محلی است؛ هیچ داده‌ای به سرویس بیرونی فرستاده نمی‌شود.
- **سفارش پرداخت‌شده محافظت می‌شود:** به «در انتظار پرداخت» برنمی‌گردد و `expire_pending_orders` هرگز آن را لغو نمی‌کند؛ لغو دستیِ سفارش پرداخت‌شده در پنل، هشدار بازگشت وجه می‌دهد.
- ورود با سقف نرخ (IP و نام‌کاربری) محافظت می‌شود. فایل `.env` از کامنت هم‌خط (`KEY=value # توضیح`) پشتیبانی می‌کند.

## ساختار

`accounts` (کاربر، OTP، SMS) · `products` (کاتالوگ، نظرات، مقایسه، پنل محصول) ·
`orders` (سبد، سفارش، `services.py` منطق کسب‌وکار، `zarinpal.py` درگاه، دستورات مدیریتی)

تحلیل کامل پروژه: فایل `تحلیل_پروژه.md` (کنار پوشه‌ی پروژه)؛ خروجی دیتابیس: `database_export.sql`

> TODO پورتفولیو: چند اسکرین‌شات از صفحه‌ی اصلی، مقایسه و پنل مدیریت به این README اضافه کنید.
