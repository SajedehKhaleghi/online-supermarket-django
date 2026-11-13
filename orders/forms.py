from django import forms

from .models import Order


class CheckoutForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["address", "delivery_time"]
        widgets = {
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "آدرس دقیق تحویل سفارش"}),
            "delivery_time": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلا: فردا بین ۱۰ تا ۱۲"}),
        }


class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["status"]
        widgets = {"status": forms.Select(attrs={"class": "form-select"})}
