from django import forms

from .models import Review, Product, Category, ProductFeature


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.Select(attrs={"class": "form-select"}),
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "نظر خود را بنویسید..."}),
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "category", "name", "brand", "description", "image",
            "price", "discount_percent", "unit", "stock", "is_active",
        ]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "brand": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "price": forms.NumberInput(attrs={"class": "form-control"}),
            "discount_percent": forms.NumberInput(attrs={"class": "form-control"}),
            "unit": forms.Select(attrs={"class": "form-select"}),
            "stock": forms.NumberInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description", "image"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


ProductFeatureFormSet = forms.inlineformset_factory(
    Product, ProductFeature, fields=["key", "value"], extra=2, can_delete=True,
    widgets={
        "key": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلا: وزن خالص"}),
        "value": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلا: 900 گرم"}),
    },
)
