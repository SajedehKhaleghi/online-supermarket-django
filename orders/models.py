from django.conf import settings
from django.db import models
from django.db.models import Sum

from products.models import Product


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart", verbose_name="کاربر")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "سبد خرید"
        verbose_name_plural = "سبدهای خرید"

    def __str__(self):
        return f"سبد خرید {self.user}"

    @property
    def total_price(self):
        return sum(item.subtotal for item in self.items.select_related("product"))

    @property
    def total_items(self):
        return self.items.aggregate(total=Sum("quantity"))["total"] or 0


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "آیتم سبد خرید"
        verbose_name_plural = "آیتم‌های سبد خرید"
        unique_together = ("cart", "product")

    def __str__(self):
        return f"{self.product} x {self.quantity}"

    @property
    def subtotal(self):
        return self.product.final_price * self.quantity


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending_payment", "در انتظار پرداخت"),
        ("processing", "در حال آماده‌سازی"),
        ("shipped", "ارسال شده"),
        ("delivered", "تحویل داده شده"),
        ("cancelled", "لغو شده"),
    ]

    # PROTECT: حذف کاربر نباید سابقه‌ی سفارش و پرداخت‌های او را (که سند مالی‌اند) پاک کند؛
    # برای مسدودکردن کاربر از is_active=False استفاده کنید.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders", verbose_name="کاربر")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending_payment", verbose_name="وضعیت")
    address = models.CharField(max_length=255, verbose_name="آدرس تحویل")
    delivery_time = models.CharField(max_length=100, verbose_name="بازه زمانی تحویل", help_text="مثلا: فردا ۱۰ تا ۱۲")
    total_price = models.PositiveIntegerField(default=0, verbose_name="مبلغ کل (تومان)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "سفارش"
        verbose_name_plural = "سفارش‌ها"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"], name="order_status_created_idx")]

    def __str__(self):
        return f"سفارش #{self.id} - {self.user}"

    @property
    def is_payable(self):
        return self.status == "pending_payment"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=200)
    price = models.PositiveIntegerField(verbose_name="قیمت واحد در زمان خرید")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "آیتم سفارش"
        verbose_name_plural = "آیتم‌های سفارش"

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

    @property
    def subtotal(self):
        return self.price * self.quantity


class Payment(models.Model):
    """پرداخت از طریق درگاه زرین‌پال (با قابلیت برگشت به حالت شبیه‌سازی در محیط توسعه)"""
    STATUS_CHOICES = [
        ("pending", "در انتظار"),
        ("success", "موفق"),
        ("failed", "ناموفق"),
    ]

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="payment")
    amount = models.PositiveIntegerField(verbose_name="مبلغ")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    authority = models.CharField(max_length=64, blank=True, db_index=True, verbose_name="کد پیگیری زرین‌پال (Authority)")
    transaction_id = models.CharField(max_length=50, blank=True, verbose_name="کد رهگیری (Ref ID)")
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "پرداخت"
        verbose_name_plural = "پرداخت‌ها"

    def __str__(self):
        return f"پرداخت سفارش #{self.order_id} - {self.get_status_display()}"

    MAX_AUTHORITIES_TO_CHECK = 5

    def known_authorities(self):
        """همه‌ی Authority هایی که برای این پرداخت گرفته شده (جدیدترین اول).
        هر بار که کاربر دوباره به درگاه می‌رود Authority تازه‌ای ساخته می‌شود؛ پرداختِ انجام‌شده روی
        Authority قدیمی‌تر هم باید پذیرفته و تطبیق داده شود، نه اینکه گم شود."""
        values = list(self.authorities.order_by("-created_at", "-id").values_list("authority", flat=True))
        if self.authority and self.authority not in values:
            values.insert(0, self.authority)   # سازگاری با داده‌های قدیمی/ثبت مستقیم
        return values


class PaymentAuthority(models.Model):
    """تاریخچه‌ی کدهای Authority صادرشده‌ی زرین‌پال برای یک پرداخت."""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="authorities")
    authority = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Authority پرداخت"
        verbose_name_plural = "Authority های پرداخت"

    def __str__(self):
        return self.authority
