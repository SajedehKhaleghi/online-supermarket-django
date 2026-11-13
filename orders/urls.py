from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/update/<int:item_id>/", views.cart_update, name="cart_update"),
    path("cart/remove/<int:item_id>/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout_view, name="checkout"),
    path("payment/<int:order_id>/", views.payment_view, name="payment"),
    path("payment/<int:order_id>/verify/", views.payment_verify_view, name="payment_verify"),
    path("payment/<int:order_id>/simulate/", views.payment_simulate_confirm, name="payment_simulate"),
    path("my-orders/", views.order_list_view, name="order_list"),
    path("my-orders/<int:order_id>/", views.order_detail_view, name="order_detail"),
    path("my-orders/<int:order_id>/cancel/", views.order_cancel_view, name="order_cancel"),

    # پنل مدیریت
    path("manage/orders/", views.admin_order_list, name="admin_order_list"),
    path("manage/orders/<int:order_id>/", views.admin_order_detail, name="admin_order_detail"),
]
