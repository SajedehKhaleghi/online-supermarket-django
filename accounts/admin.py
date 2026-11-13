from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, OTPCode


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "phone_number", "email", "is_phone_verified", "is_staff")
    search_fields = ("username", "phone_number", "email")
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {"classes": ("wide",), "fields": ("phone_number",)}),
    )
    fieldsets = UserAdmin.fieldsets + (
        ("اطلاعات تکمیلی", {"fields": ("phone_number", "address", "is_phone_verified")}),
    )


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "created_at", "is_used", "attempts")
    list_filter = ("is_used",)
    exclude = ("code",)
    readonly_fields = ("phone_number", "created_at", "is_used", "attempts")
