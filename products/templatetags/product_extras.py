from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """امکان دسترسی به مقدار دیکشنری با کلید متغیر داخل تمپلیت (برای جدول مقایسه محصولات)"""
    if not dictionary:
        return None
    return dictionary.get(key)
