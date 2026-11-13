from django.core.management.base import BaseCommand

from orders.services import expire_pending_orders


class Command(BaseCommand):
    help = "سفارش‌های پرداخت‌نشده‌ی قدیمی را لغو و موجودی را آزاد می‌کند (با cron هر ۵ تا ۱۵ دقیقه اجرا شود)."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=None, help="مهلت به دقیقه (پیش‌فرض از settings)")

    def handle(self, *args, **options):
        cancelled, recovered = expire_pending_orders(options["minutes"])
        self.stdout.write(self.style.SUCCESS(f"لغو شده: {cancelled} | پرداخت‌های بازیابی‌شده: {recovered}"))
