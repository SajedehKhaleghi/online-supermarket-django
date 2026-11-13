from django.contrib import admin

from .models import Cart, CartItem, Order, OrderItem, Payment, PaymentAuthority


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "total_price", "created_at")
    list_filter = ("status",)
    inlines = [OrderItemInline]


class PaymentAuthorityInline(admin.TabularInline):
    model = PaymentAuthority
    extra = 0
    readonly_fields = ("authority", "created_at")
    can_delete = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    inlines = [PaymentAuthorityInline]
    list_display = ("order", "amount", "status", "authority", "transaction_id", "paid_at")


admin.site.register(Cart)
admin.site.register(CartItem)
