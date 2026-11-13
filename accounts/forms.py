from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_digits(value):
    """ارقام فارسی/عربی را به لاتین تبدیل می‌کند و فاصله‌ها را حذف می‌کند."""
    return (value or "").translate(_FA_DIGITS).strip()


class RegisterForm(UserCreationForm):
    phone_number = forms.CharField(
        label="شماره موبایل",
        max_length=11,
        widget=forms.TextInput(attrs={"placeholder": "09xxxxxxxxx", "class": "form-control"}),
    )

    class Meta:
        model = User
        fields = ["username", "phone_number", "password1", "password2"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_phone_number(self):
        phone = normalize_digits(self.cleaned_data["phone_number"])
        if not (phone.isascii() and phone.isdigit()) or len(phone) != 11 or not phone.startswith("09"):
            raise forms.ValidationError("شماره موبایل معتبر نیست. مثال: 09123456789")
        # ثبت‌نامِ تاییدنشده (غیرفعال و بدون OTP موفق) شماره را اشغال نمی‌کند؛ وگرنه هر کسی می‌توانست
        # با ثبت‌نام الکی شماره‌ی دیگران را ۳۰ دقیقه قفل کند. این رکوردها هنگام ثبت‌نام جدید پاک می‌شوند.
        taken = User.objects.filter(phone_number=phone).exclude(
            is_active=False, is_phone_verified=False, is_staff=False, is_superuser=False,
        )
        if taken.exists():
            raise forms.ValidationError("این شماره موبایل قبلاً ثبت‌نام کرده است.")
        return phone

    def validate_unique(self):
        # یکتایی شماره را clean_phone_number بررسی می‌کند (با استثنای ثبت‌نام‌های تاییدنشده)؛
        # بررسی پیش‌فرض مدل آن‌ها را هم «تکراری» می‌دانست و فرم را قبل از آزادشدن شماره رد می‌کرد.
        exclude = self._get_validation_exclusions()
        exclude.add("phone_number")
        try:
            self.instance.validate_unique(exclude=exclude)
        except forms.ValidationError as e:
            self._update_errors(e)


class OTPVerifyForm(forms.Form):
    code = forms.CharField(
        label="کد تایید پیامکی",
        max_length=6,
        widget=forms.TextInput(attrs={"class": "form-control text-center", "placeholder": "------"}),
    )

    def clean_code(self):
        return normalize_digits(self.cleaned_data["code"])


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "address"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
