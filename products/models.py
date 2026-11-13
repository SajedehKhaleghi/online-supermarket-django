from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


def _unique_slug(model, name, pk, fallback):
    """slug یکتا می‌سازد؛ اگر نام فقط نویسه‌ی غیرقابل‌تبدیل داشت (مثل «!!!») از fallback استفاده می‌کند
    تا slug خالی (و NoReverseMatch در get_absolute_url) پیش نیاید."""
    base = slugify(name, allow_unicode=True) or fallback
    slug, counter = base, 1
    while model.objects.filter(slug=slug).exclude(pk=pk).exists():
        counter += 1
        slug = f"{base}-{counter}"
    return slug


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="نام دسته")
    slug = models.SlugField(max_length=120, unique=True, blank=True, allow_unicode=True)
    description = models.TextField(blank=True, verbose_name="توضیحات")
    image = models.ImageField(upload_to="categories/", blank=True, null=True, verbose_name="تصویر")

    class Meta:
        verbose_name = "دسته‌بندی"
        verbose_name_plural = "دسته‌بندی‌ها"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Category, self.name, self.pk, "category")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("products:category_detail", args=[self.slug])


class ProductQuerySet(models.QuerySet):
    def with_ratings(self):
        """میانگین امتیاز و تعداد نظرات را در همان query می‌آورد (جلوگیری از N+1 در لیست‌ها)."""
        return self.annotate(
            avg_rating_annotated=models.Avg("reviews__rating"),
            review_count_annotated=models.Count("reviews", distinct=True),
        ).order_by("-created_at", "-id")  # GROUP BY ترتیب پیش‌فرض Meta را نادیده می‌گیرد

    def active(self):
        return self.filter(is_active=True)


class Product(models.Model):
    UNIT_CHOICES = [
        ("kg", "کیلوگرم"),
        ("g", "گرم"),
        ("piece", "عدد"),
        ("liter", "لیتر"),
        ("pack", "بسته"),
    ]

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="products", verbose_name="دسته‌بندی")
    name = models.CharField(max_length=200, verbose_name="نام محصول")
    slug = models.SlugField(max_length=220, unique=True, blank=True, allow_unicode=True)
    brand = models.CharField(max_length=100, blank=True, verbose_name="برند")
    description = models.TextField(verbose_name="توضیحات")
    image = models.ImageField(upload_to="products/", blank=True, null=True, verbose_name="تصویر")
    price = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="قیمت (تومان)")
    discount_percent = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)], verbose_name="درصد تخفیف")
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default="piece", verbose_name="واحد")
    stock = models.PositiveIntegerField(default=0, verbose_name="موجودی")
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = "محصول"
        verbose_name_plural = "محصولات"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Product, self.name, self.pk, "product")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("products:product_detail", args=[self.slug])

    @property
    def final_price(self):
        if self.discount_percent:
            percent = min(self.discount_percent, 100)
            return self.price * (100 - percent) // 100
        return self.price

    @property
    def average_rating(self):
        if hasattr(self, "avg_rating_annotated"):
            return round(self.avg_rating_annotated, 1) if self.avg_rating_annotated else 0
        agg = self.reviews.aggregate(avg=models.Avg("rating"))["avg"]
        return round(agg, 1) if agg else 0

    @property
    def review_count(self):
        if hasattr(self, "review_count_annotated"):
            return self.review_count_annotated
        return self.reviews.count()

    @property
    def in_stock(self):
        return self.stock > 0


class ProductFeature(models.Model):
    """ویژگی‌های مشخص هر محصول به‌صورت کلید-مقدار، مثل: وزن خالص=۹۰۰ گرم"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="features", verbose_name="محصول")
    key = models.CharField(max_length=100, verbose_name="عنوان ویژگی")
    value = models.CharField(max_length=200, verbose_name="مقدار")

    class Meta:
        verbose_name = "ویژگی محصول"
        verbose_name_plural = "ویژگی‌های محصول"

    def __str__(self):
        return f"{self.key}: {self.value}"


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews", verbose_name="محصول")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews", verbose_name="کاربر")
    rating = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)], verbose_name="امتیاز")
    comment = models.TextField(blank=True, verbose_name="نظر")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "نظر و امتیاز"
        verbose_name_plural = "نظرات و امتیازها"
        unique_together = ("product", "user")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} -> {self.product} ({self.rating})"
