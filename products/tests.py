from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from orders.models import Order, OrderItem
from .models import Category, Product, ProductFeature, Review


def make_product(category, name, price=10000, stock=10, **kw):
    return Product.objects.create(category=category, name=name, description="d", price=price, stock=stock, **kw)


class CompareTests(TestCase):
    def setUp(self):
        self.dairy = Category.objects.create(name="لبنیات")
        self.fruit = Category.objects.create(name="میوه")
        self.items = [make_product(self.dairy, f"شیر {i}") for i in range(5)]
        self.apple = make_product(self.fruit, "سیب")

    def add(self, product):
        return self.client.post(reverse("products:compare_add", args=[product.id]))

    def test_add_requires_post(self):
        url = reverse("products:compare_add", args=[self.items[0].id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.get(reverse("products:compare_clear")).status_code, 405)

    def test_add_and_limit_of_four(self):
        for p in self.items[:4]:
            self.add(p)
        self.add(self.items[4])
        self.assertEqual(len(self.client.session["compare_list"]), 4)
        self.assertNotIn(self.items[4].id, self.client.session["compare_list"])

    def test_duplicate_not_added_twice(self):
        self.add(self.items[0])
        self.add(self.items[0])
        self.assertEqual(self.client.session["compare_list"], [self.items[0].id])

    def test_other_category_rejected(self):
        self.add(self.items[0])
        self.add(self.apple)
        self.assertEqual(self.client.session["compare_list"], [self.items[0].id])

    def test_inactive_product_cannot_be_added(self):
        self.items[0].is_active = False
        self.items[0].save()
        self.assertEqual(self.add(self.items[0]).status_code, 404)

    def test_compare_view_keeps_order_and_collects_features(self):
        ProductFeature.objects.create(product=self.items[0], key="وزن", value="1kg")
        ProductFeature.objects.create(product=self.items[1], key="چربی", value="3")
        self.add(self.items[1])
        self.add(self.items[0])
        response = self.client.get(reverse("products:compare"))
        self.assertEqual([p.id for p in response.context["products"]], [self.items[1].id, self.items[0].id])
        self.assertEqual(set(response.context["feature_keys"]), {"وزن", "چربی"})

    def test_remove_and_clear(self):
        self.add(self.items[0])
        self.add(self.items[1])
        self.client.post(reverse("products:compare_remove", args=[self.items[0].id]))
        self.assertEqual(self.client.session["compare_list"], [self.items[1].id])
        self.client.post(reverse("products:compare_clear"))
        self.assertEqual(self.client.session["compare_list"], [])

    def test_open_redirect_is_blocked(self):
        response = self.client.post(
            reverse("products:compare_add", args=[self.items[0].id]), HTTP_REFERER="https://evil.example/x"
        )
        self.assertRedirects(response, reverse("products:product_list"), fetch_redirect_response=False)


class ProductListTests(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(name="c")
        self.p = make_product(self.cat, "برنج", price=100)

    def test_garbage_price_filters_do_not_crash(self):
        response = self.client.get(reverse("products:product_list"), {"min_price": "abc", "max_price": "1; DROP"})
        self.assertEqual(response.status_code, 200)

    def test_price_filter_works(self):
        make_product(self.cat, "گران", price=5000)
        response = self.client.get(reverse("products:product_list"), {"min_price": "1000"})
        self.assertEqual([p.name for p in response.context["page_obj"]], ["گران"])

    def test_rating_annotation_matches_property(self):
        u1 = User.objects.create_user("a", password="x", phone_number="09120000011")
        u2 = User.objects.create_user("b", password="x", phone_number="09120000012")
        Review.objects.create(product=self.p, user=u1, rating=5)
        Review.objects.create(product=self.p, user=u2, rating=4)
        annotated = Product.objects.with_ratings().get(pk=self.p.pk)
        self.assertEqual(annotated.average_rating, 4.5)
        self.assertEqual(annotated.review_count, 2)
        self.assertEqual(Product.objects.get(pk=self.p.pk).average_rating, 4.5)

    def test_list_query_count_does_not_grow_with_products(self):
        for i in range(10):
            make_product(self.cat, f"p{i}")
        with self.assertNumQueries(3):  # count / categories / page — بدون N+1
            self.client.get(reverse("products:product_list"))


class AdminProductDeleteTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("s", password="x", phone_number="09120000021", is_staff=True)
        self.client.force_login(self.staff)
        self.cat = Category.objects.create(name="c")

    def test_unused_product_is_deleted(self):
        p = make_product(self.cat, "x")
        self.client.post(reverse("products:admin_product_delete", args=[p.id]))
        self.assertFalse(Product.objects.filter(pk=p.pk).exists())

    def test_product_in_orders_is_deactivated_not_deleted(self):
        p = make_product(self.cat, "x")
        order = Order.objects.create(user=self.staff, address="a", delivery_time="t", total_price=1)
        OrderItem.objects.create(order=order, product=p, product_name="x", price=1, quantity=1)
        self.client.post(reverse("products:admin_product_delete", args=[p.id]))
        p.refresh_from_db()
        self.assertFalse(p.is_active)

    def test_non_staff_cannot_access(self):
        self.client.logout()
        response = self.client.get(reverse("products:admin_product_list"))
        self.assertEqual(response.status_code, 302)
