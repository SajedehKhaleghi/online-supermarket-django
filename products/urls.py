from django.urls import path

from . import views

app_name = "products"

urlpatterns = [
    path("", views.home_view, name="home"),
    path("products/", views.product_list_view, name="product_list"),
    path("category/<str:slug>/", views.category_detail_view, name="category_detail"),
    path("product/<str:slug>/", views.product_detail_view, name="product_detail"),

    # مقایسه محصولات
    path("compare/", views.compare_view, name="compare"),
    path("compare/add/<int:product_id>/", views.compare_add, name="compare_add"),
    path("compare/remove/<int:product_id>/", views.compare_remove, name="compare_remove"),
    path("compare/clear/", views.compare_clear, name="compare_clear"),

    # پنل مدیریت
    path("manage/products/", views.admin_product_list, name="admin_product_list"),
    path("manage/products/add/", views.admin_product_create, name="admin_product_create"),
    path("manage/products/<int:pk>/edit/", views.admin_product_edit, name="admin_product_edit"),
    path("manage/products/<int:pk>/delete/", views.admin_product_delete, name="admin_product_delete"),
    path("manage/categories/", views.admin_category_list, name="admin_category_list"),
    path("manage/categories/add/", views.admin_category_create, name="admin_category_create"),
]
