from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.models import Payment
from orders.services import reconcile_payment
from orders import zarinpal


class Command(BaseCommand):
    help = "پرداخت‌های معلق (دارای Authority) را با زرین‌پال تطبیق می‌دهد؛ برای زمانی که callback کاربر نرسیده است."

    def add_arguments(self, parser):
        parser.add_argument("--min-age", type=int, default=3, help="حداقل سن پرداخت به دقیقه (پیش‌فرض ۳)")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options["min_age"])
        # شامل سفارش‌های تازه لغوشده هم می‌شود تا پرداخت دیرهنگام (callback گم‌شده) هم پیدا شود
        payments = Payment.objects.filter(
            status__in=["pending", "failed"],
            order__status__in=["pending_payment", "cancelled"],
            order__created_at__lt=cutoff,
            # Authority زرین‌پال عمر کوتاهی دارد؛ پنجره‌ی کوتاه یعنی پرداخت‌های ناموفق/انصرافی
            # ساعت‌ها بعد هر بار دوباره از درگاه استعلام نمی‌شوند.
            order__created_at__gt=timezone.now() - timedelta(minutes=settings.PAYMENT_RECONCILE_WINDOW_MINUTES),
        ).exclude(authority="").select_related("order")
        ok = checked = 0
        for payment in payments:
            checked += 1
            if reconcile_payment(payment) == zarinpal.VERIFY_SUCCESS:
                ok += 1
        self.stdout.write(self.style.SUCCESS(f"بررسی‌شده: {checked} | موفق: {ok}"))
