from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.models import Category, Product, ProductFeature


CATEGORIES = {
    "لبنیات": [
        {"name": "شیر پرچرب پگاه", "brand": "پگاه", "price": 39000, "unit": "liter",
         "desc": "شیر پاستوریزه پرچرب یک لیتری، غنی‌شده با ویتامین D.",
         "features": {"وزن خالص": "1 لیتر", "درصد چربی": "3.2٪", "تاریخ انقضا": "10 روز پس از تولید"}},
        {"name": "ماست کم‌چرب کاله", "brand": "کاله", "price": 32000, "unit": "kg",
         "desc": "ماست کم‌چرب طبیعی، مناسب رژیم غذایی.",
         "features": {"وزن خالص": "900 گرم", "درصد چربی": "1.5٪"}},
        {"name": "پنیر سفید UF کاله", "brand": "کاله", "price": 89000, "unit": "pack",
         "desc": "پنیر سفید فرآوری‌شده با روش اولترافیلتراسیون.",
         "features": {"وزن خالص": "400 گرم", "بسته‌بندی": "ظرف پلاستیکی"}},
    ],
    "میوه و تره‌بار": [
        {"name": "سیب قرمز درجه‌یک", "brand": "", "price": 68000, "unit": "kg",
         "desc": "سیب قرمز تازه و آبدار، مستقیم از باغات شمال.",
         "features": {"مبدا": "آمل", "درجه‌بندی": "یک"}},
        {"name": "موز صادراتی", "brand": "", "price": 75000, "unit": "kg",
         "desc": "موز تازه و رسیده، مناسب مصرف روزانه.",
         "features": {"مبدا": "اکوادور"}},
        {"name": "گوجه‌فرنگی بوته‌ای", "brand": "", "price": 32000, "unit": "kg",
         "desc": "گوجه‌فرنگی تازه بوته‌ای، مناسب سالاد و پخت.",
         "features": {"مبدا": "جیرفت"}},
    ],
    "نان و غلات": [
        {"name": "نان تست سنگک", "brand": "", "price": 25000, "unit": "pack",
         "desc": "نان تست تهیه‌شده از آرد سنگک، بدون مواد نگه‌دارنده.",
         "features": {"وزن خالص": "300 گرم", "تعداد": "8 عدد"}},
        {"name": "برنج طارم هاشمی", "brand": "", "price": 320000, "unit": "kg",
         "desc": "برنج طارم هاشمی درجه‌یک، محصول گیلان.",
         "features": {"وزن بسته": "5 کیلوگرم", "مبدا": "فومن"}},
    ],
    "نوشیدنی": [
        {"name": "آب معدنی دماوند", "brand": "دماوند", "price": 8000, "unit": "liter",
         "desc": "آب معدنی طبیعی بطری 1.5 لیتری.",
         "features": {"حجم": "1.5 لیتر"}},
        {"name": "نوشابه کوکاکولا", "brand": "Coca-Cola", "price": 22000, "unit": "piece",
         "desc": "نوشابه گازدار قوطی 330 میلی‌لیتری.",
         "features": {"حجم": "330 میلی‌لیتر"}},
    ],
    "خشکبار و تنقلات": [
        {"name": "پسته اکبری ممتاز", "brand": "", "price": 890000, "unit": "kg",
         "desc": "پسته اکبری ممتاز درجه‌یک، محصول رفسنجان.",
         "features": {"مبدا": "رفسنجان", "درجه‌بندی": "ممتاز"}},
        {"name": "چیپس سیب‌زمینی چی توز", "brand": "چی توز", "price": 45000, "unit": "pack",
         "desc": "چیپس سیب‌زمینی نمکی، بسته خانواده.",
         "features": {"وزن خالص": "150 گرم"}},
    ],
}


class Command(BaseCommand):
    help = "Seed the database with realistic supermarket sample data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo-admin", action="store_true",
            help="ساخت کاربر ادمین نمونه (admin / Admin@12345) — فقط در حالت DEBUG مجاز است",
        )

    def handle(self, *args, **options):
        if options["demo_admin"]:
            self._create_demo_admin()
        for cat_name, products in CATEGORIES.items():
            category, _ = Category.objects.get_or_create(name=cat_name)
            for p in products:
                if Product.objects.filter(name=p["name"]).exists():
                    continue
                product = Product.objects.create(
                    category=category,
                    name=p["name"],
                    brand=p.get("brand", ""),
                    description=p["desc"],
                    price=p["price"],
                    unit=p["unit"],
                    stock=50,
                    discount_percent=10 if p["name"] in ("سیب قرمز درجه‌یک", "نوشابه کوکاکولا") else 0,
                )
                for key, value in p["features"].items():
                    ProductFeature.objects.create(product=product, key=key, value=value)
                self.stdout.write(self.style.SUCCESS(f"ساخته شد: {product.name}"))

        self.stdout.write(self.style.SUCCESS("داده‌های نمونه با موفقیت اضافه شدند."))

    def _create_demo_admin(self):
        if not settings.DEBUG:
            raise CommandError("ساخت ادمین نمونه با رمز ثابت فقط در DEBUG مجاز است؛ از createsuperuser استفاده کنید.")
        from accounts.models import User
        if User.objects.filter(username="admin").exists():
            self.stdout.write("ادمین نمونه از قبل وجود دارد.")
            return
        User.objects.create_superuser(
            username="admin", password="Admin@12345", email="admin@example.com",
            phone_number="09120000000", is_phone_verified=True,
        )
        self.stdout.write(self.style.WARNING("ادمین نمونه ساخته شد: admin / Admin@12345 (فقط برای توسعه!)"))
