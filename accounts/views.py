from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import F
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from orders.models import Order
from . import sms, throttle
from .forms import RegisterForm, OTPVerifyForm, ProfileUpdateForm
from .models import User, OTPCode

COMPARE_SESSION_KEY = "compare_list"


def purge_unverified_users():
    """کاربران ثبت‌نام‌شده‌ای که OTP را تایید نکرده‌اند و مهلتشان گذشته پاک می‌شوند
    تا شماره/نام‌کاربری برای ثبت‌نام واقعی آزاد بماند."""
    cutoff = timezone.now() - timedelta(minutes=settings.UNVERIFIED_USER_TTL_MINUTES)
    return User.objects.filter(
        is_active=False, is_phone_verified=False, is_staff=False, date_joined__lt=cutoff
    ).delete()


HOUR = 3600
SENT, THROTTLED, FAILED = "sent", "throttled", "failed"


def _send_new_otp(user):
    """کد جدید می‌سازد و پیامک می‌کند. اگر سقف ارسال به این شماره پر باشد، پیامکی ارسال نمی‌شود."""
    if throttle.is_limited("otp_sms", user.phone_number, settings.OTP_SMS_LIMIT_PER_PHONE_PER_HOUR, HOUR):
        return THROTTLED
    throttle.hit("otp_sms", user.phone_number, HOUR)
    otp, plain = OTPCode.generate_code(user.phone_number)
    try:
        sms.send_otp(user.phone_number, plain)
        return SENT
    except sms.SMSError:
        return FAILED


def register_view(request):
    purge_unverified_users()
    OTPCode.purge_old()
    if request.method == "POST":
        ip = throttle.client_ip(request)
        if throttle.is_limited("register", ip, settings.REGISTER_LIMIT_PER_IP_PER_HOUR, HOUR):
            messages.error(request, "تعداد تلاش‌های ثبت‌نام زیاد بود. لطفاً بعداً دوباره تلاش کنید.")
            return render(request, "accounts/register.html", {"form": RegisterForm()}, status=429)
        form = RegisterForm(request.POST)
        if form.is_valid():
            throttle.hit("register", ip, HOUR)
            # ثبت‌نام ناتمامِ قبلیِ همین شماره (اگر باشد) آزاد می‌شود تا مالک واقعی شماره بتواند ثبت‌نام کند
            User.objects.filter(
                phone_number=form.cleaned_data["phone_number"],
                is_active=False, is_phone_verified=False, is_staff=False, is_superuser=False,
            ).delete()
            user = form.save(commit=False)
            # تا قبل از تایید OTP حساب غیرفعال است؛ بنابراین امکان ورود ندارد.
            user.is_active = False
            user.is_phone_verified = False
            user.save()

            request.session["pending_user_id"] = user.id
            result = _send_new_otp(user)
            if result == SENT:
                messages.info(request, "کد تایید برای شما پیامک شد.")
            elif result == THROTTLED:
                messages.error(request, "تعداد پیامک‌های ارسالی به این شماره زیاد بوده است. یک ساعت بعد دوباره تلاش کنید.")
            else:
                messages.error(request, "ارسال پیامک ناموفق بود. چند لحظه بعد دوباره «ارسال مجدد کد» را بزنید.")
            return redirect("accounts:verify_otp")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


def verify_otp_view(request):
    user_id = request.session.get("pending_user_id")
    if not user_id:
        return redirect("accounts:register")
    user = User.objects.filter(id=user_id, is_active=False, is_phone_verified=False).first()
    if user is None:
        request.session.pop("pending_user_id", None)
        messages.error(request, "مهلت ثبت‌نام شما تمام شده است. دوباره ثبت‌نام کنید.")
        return redirect("accounts:register")

    if request.method == "POST":
        ip = throttle.client_ip(request)
        if throttle.is_limited("otp_verify", ip, settings.OTP_VERIFY_LIMIT_PER_IP_PER_HOUR, HOUR):
            messages.error(request, "تعداد تلاش‌ها زیاد بود. لطفاً بعداً دوباره تلاش کنید.")
            return render(request, "accounts/verify_otp.html", {
                "form": OTPVerifyForm(), "pending_user": user,
                "resend_cooldown": settings.OTP_RESEND_COOLDOWN_SECONDS,
            }, status=429)
        throttle.hit("otp_verify", ip, HOUR)
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            otp = OTPCode.objects.filter(phone_number=user.phone_number, is_used=False).order_by("-created_at").first()

            if otp is None or otp.is_expired:
                messages.error(request, "کد منقضی شده است. «ارسال مجدد کد» را بزنید.")
            elif otp.is_locked:
                messages.error(request, "تعداد تلاش‌های اشتباه زیاد بود. «ارسال مجدد کد» را بزنید.")
            elif otp.check_code(form.cleaned_data["code"]):
                otp.is_used = True
                otp.save(update_fields=["is_used"])
                user.is_active = True
                user.is_phone_verified = True
                user.save(update_fields=["is_active", "is_phone_verified"])
                request.session.pop("pending_user_id", None)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                messages.success(request, "ثبت‌نام شما با موفقیت تکمیل شد.")
                return redirect("products:home")
            else:
                # افزایش اتمیک؛ درخواست‌های هم‌زمان نمی‌توانند سقف تلاش را دور بزنند
                OTPCode.objects.filter(pk=otp.pk).update(attempts=F("attempts") + 1)
                messages.error(request, "کد وارد شده اشتباه است.")
    else:
        form = OTPVerifyForm()
    return render(request, "accounts/verify_otp.html", {
        "form": form, "pending_user": user,
        "resend_cooldown": settings.OTP_RESEND_COOLDOWN_SECONDS,
    })


@require_POST
def resend_otp_view(request):
    user_id = request.session.get("pending_user_id")
    user = User.objects.filter(id=user_id, is_active=False, is_phone_verified=False).first() if user_id else None
    if user is None:
        return redirect("accounts:register")

    last = OTPCode.objects.filter(phone_number=user.phone_number).order_by("-created_at").first()
    if last and timezone.now() < last.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS):
        messages.warning(request, "لطفاً کمی صبر کنید و دوباره تلاش کنید.")
    else:
        result = _send_new_otp(user)
        if result == SENT:
            messages.info(request, "کد جدید ارسال شد.")
        elif result == THROTTLED:
            messages.error(request, "تعداد پیامک‌های ارسالی به این شماره زیاد بوده است. یک ساعت بعد دوباره تلاش کنید.")
        else:
            messages.error(request, "ارسال پیامک ناموفق بود.")
    return redirect("accounts:verify_otp")


class ShopLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    WINDOW = 15 * 60

    def post(self, request, *args, **kwargs):
        ip = throttle.client_ip(request)
        username = (request.POST.get("username") or "").strip().lower()[:150]
        if (throttle.is_limited("login_ip", ip, settings.LOGIN_FAILURE_LIMIT_PER_IP, self.WINDOW)
                or (username and throttle.is_limited(
                    "login_user", username, settings.LOGIN_FAILURE_LIMIT_PER_USERNAME, self.WINDOW))):
            messages.error(request, "تلاش‌های ناموفق زیاد بود. چند دقیقه بعد دوباره تلاش کنید.")
            return render(request, self.template_name, {"form": self.get_form()}, status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        throttle.hit("login_ip", throttle.client_ip(self.request), self.WINDOW)
        username = (self.request.POST.get("username") or "").strip().lower()[:150]
        if username:
            throttle.hit("login_user", username, self.WINDOW)
        return super().form_invalid(form)

    def form_valid(self, form):
        throttle.reset("login_user", form.get_user().get_username().lower())
        return super().form_valid(form)


@require_POST
def logout_view(request):
    # لیست مقایسه با خروج کاربر از بین نرود
    compare_list = request.session.get(COMPARE_SESSION_KEY, [])
    logout(request)
    if compare_list:
        request.session[COMPARE_SESSION_KEY] = compare_list
    messages.info(request, "با موفقیت خارج شدید.")
    return redirect("products:home")


@login_required
def dashboard_view(request):
    orders = Order.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "accounts/dashboard.html", {"orders": orders[:5], "has_more": orders.count() > 5})


@login_required
def profile_edit_view(request):
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "پروفایل با موفقیت بروزرسانی شد.")
            return redirect("accounts:dashboard")
    else:
        form = ProfileUpdateForm(instance=request.user)
    return render(request, "accounts/profile_edit.html", {"form": form})
