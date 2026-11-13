from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("verify-otp/", views.verify_otp_view, name="verify_otp"),
    path("verify-otp/resend/", views.resend_otp_view, name="resend_otp"),
    path("login/", views.ShopLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("profile/edit/", views.profile_edit_view, name="profile_edit"),
]
