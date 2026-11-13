from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import ReviewForm, ProductForm, CategoryForm, ProductFeatureFormSet
from .models import Category, Product


def staff_required(user):
    return user.is_authenticated and user.is_staff


def _to_int(raw):
    """رشته را به عدد صحیح غیرمنفی تبدیل می‌کند؛ ورودی نامعتبر (مثل «²») یا خیلی بزرگ → None.
    (str.isdigit() برای «²» True برمی‌گرداند ولی int() خطا می‌دهد.)"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value < 2**63 else None


def home_view(request):
    categories = Category.objects.all()
    base = Product.objects.active().with_ratings().select_related("category")
    latest_products = base[:8]
    discounted = base.filter(discount_percent__gt=0)[:8]
    return render(request, "products/home.html", {
        "categories": categories,
        "latest_products": latest_products,
        "discounted": discounted,
    })


def product_list_view(request):
    products = Product.objects.active().with_ratings().select_related("category")

    query = request.GET.get("q", "")
    category_slug = request.GET.get("category", "")
    min_price = request.GET.get("min_price", "")
    max_price = request.GET.get("max_price", "")
    sort = request.GET.get("sort", "")

    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query) | Q(brand__icontains=query))
    if category_slug:
        products = products.filter(category__slug=category_slug)
    # ورودی‌های غیرعددی نادیده گرفته می‌شوند (قبلاً باعث خطای ۵۰۰ می‌شد)
    low, high = _to_int(min_price), _to_int(max_price)
    if low is not None:
        products = products.filter(price__gte=low)
    if high is not None:
        products = products.filter(price__lte=high)

    if sort == "price_asc":
        products = products.order_by("price", "-id")   # tie-breaker برای صفحه‌بندی پایدار
    elif sort == "price_desc":
        products = products.order_by("-price", "-id")
    elif sort == "newest":
        products = products.order_by("-created_at", "-id")

    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "products/product_list.html", {
        "page_obj": page_obj,
        "categories": Category.objects.all(),
        "query": query,
        "category_slug": category_slug,
        "min_price": min_price,
        "max_price": max_price,
        "sort": sort,
    })


def category_detail_view(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = category.products.active().with_ratings().select_related("category")
    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "products/category_detail.html", {"category": category, "page_obj": page_obj})


def product_detail_view(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    reviews = product.reviews.select_related("user")
    user_review = None
    form = ReviewForm()

    if request.user.is_authenticated:
        user_review = reviews.filter(user=request.user).first()

    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.error(request, "برای ثبت نظر ابتدا وارد حساب کاربری خود شوید.")
            return redirect("accounts:login")
        form = ReviewForm(request.POST, instance=user_review)
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            review.user = request.user
            review.save()
            messages.success(request, "نظر شما ثبت شد.")
            return redirect("products:product_detail", slug=slug)

    related_products = (
        Product.objects.active().with_ratings().select_related("category")
        .filter(category=product.category).exclude(id=product.id)[:4]
    )

    return render(request, "products/product_detail.html", {
        "product": product,
        "reviews": reviews,
        "form": form,
        "related_products": related_products,
    })


# ---------- مقایسه محصولات (Session-based، بدون نیاز به لاگین) ----------

COMPARE_SESSION_KEY = "compare_list"
COMPARE_MAX_ITEMS = 4


def _safe_back(request, fallback):
    """بازگشت به صفحه‌ی قبل، فقط اگر به همین سایت تعلق داشته باشد (جلوگیری از open redirect)."""
    referer = request.META.get("HTTP_REFERER")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect(fallback)


@require_POST
def compare_add(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    compare_list = request.session.get(COMPARE_SESSION_KEY, [])

    if product.id in compare_list:
        messages.info(request, f"{product.name} از قبل در لیست مقایسه است.")
    elif len(compare_list) >= COMPARE_MAX_ITEMS:
        messages.warning(request, f"حداکثر {COMPARE_MAX_ITEMS} محصول را می‌توانید هم‌زمان مقایسه کنید.")
    else:
        # مقایسه فقط بین محصولات هم‌دسته معنی دارد
        first = Product.objects.filter(id__in=compare_list).first()
        if first and first.category_id != product.category_id:
            messages.warning(
                request,
                f"فقط محصولات هم‌دسته قابل مقایسه‌اند. لیست فعلی از دسته‌ی «{first.category.name}» است؛ "
                "برای مقایسه‌ی دسته‌ی دیگر، ابتدا لیست را پاک کنید.",
            )
        else:
            compare_list.append(product.id)
            request.session[COMPARE_SESSION_KEY] = compare_list
            messages.success(request, f"{product.name} به لیست مقایسه اضافه شد.")

    return _safe_back(request, "products:product_list")


@require_POST
def compare_remove(request, product_id):
    compare_list = request.session.get(COMPARE_SESSION_KEY, [])
    if product_id in compare_list:
        compare_list.remove(product_id)
        request.session[COMPARE_SESSION_KEY] = compare_list
    return redirect("products:compare")


@require_POST
def compare_clear(request):
    request.session[COMPARE_SESSION_KEY] = []
    return redirect("products:compare")


def compare_view(request):
    compare_list = request.session.get(COMPARE_SESSION_KEY, [])
    products = list(
        Product.objects.active().with_ratings()
        .filter(id__in=compare_list).select_related("category").prefetch_related("features")
    )
    # حفظ ترتیب افزودن کاربر
    order = {pid: i for i, pid in enumerate(compare_list)}
    products.sort(key=lambda p: order[p.id])

    # مجموعه‌ی یکتای همه‌ی عنوان‌ ویژگی‌ها برای ساخت جدول مقایسه
    feature_keys = []
    for p in products:
        p.feature_map = {f.key: f.value for f in p.features.all()}
        for key in p.feature_map:
            if key not in feature_keys:
                feature_keys.append(key)

    return render(request, "products/compare.html", {
        "products": products,
        "feature_keys": feature_keys,
        "max_items": COMPARE_MAX_ITEMS,
    })


# ---------- پنل مدیریت محصولات (ادمین/کارمند فروشگاه) ----------

@user_passes_test(staff_required)
def admin_product_list(request):
    products = Product.objects.select_related("category").order_by("-created_at")
    page_obj = Paginator(products, 20).get_page(request.GET.get("page"))
    return render(request, "products/admin/product_list.html", {"products": page_obj, "page_obj": page_obj})


@user_passes_test(staff_required)
def admin_product_create(request):
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        formset = ProductFeatureFormSet(request.POST, instance=Product())
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                product = form.save()
                formset.instance = product
                formset.save()
            messages.success(request, "محصول با موفقیت اضافه شد.")
            return redirect("products:admin_product_list")
    else:
        form = ProductForm()
        formset = ProductFeatureFormSet()
    return render(request, "products/admin/product_form.html", {"form": form, "formset": formset, "title": "افزودن محصول"})


@user_passes_test(staff_required)
def admin_product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        formset = ProductFeatureFormSet(request.POST, instance=product)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "محصول ویرایش شد.")
            return redirect("products:admin_product_list")
    else:
        form = ProductForm(instance=product)
        formset = ProductFeatureFormSet(instance=product)
    return render(request, "products/admin/product_form.html", {"form": form, "formset": formset, "title": "ویرایش محصول"})


@user_passes_test(staff_required)
def admin_product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        if product.orderitem_set.exists():
            # محصولی که در سفارش‌ها استفاده شده، حذف فیزیکی نمی‌شود تا تاریخچه‌ی سفارش‌ها حفظ شود
            product.is_active = False
            product.save(update_fields=["is_active"])
            messages.warning(request, "این محصول در سفارش‌های قبلی وجود دارد؛ به‌جای حذف، غیرفعال شد.")
        else:
            product.delete()
            messages.success(request, "محصول حذف شد.")
        return redirect("products:admin_product_list")
    return render(request, "products/admin/product_confirm_delete.html", {"product": product})


@user_passes_test(staff_required)
def admin_category_list(request):
    categories = Category.objects.all()
    return render(request, "products/admin/category_list.html", {"categories": categories})


@user_passes_test(staff_required)
def admin_category_create(request):
    if request.method == "POST":
        form = CategoryForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "دسته‌بندی اضافه شد.")
            return redirect("products:admin_category_list")
    else:
        form = CategoryForm()
    return render(request, "products/admin/category_form.html", {"form": form, "title": "افزودن دسته‌بندی"})
