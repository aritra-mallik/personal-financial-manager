# core/forms.py
from django import forms
from .models import UserPreference

class UserPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ["currency", "language", "theme"]

        widgets = {
            "currency": forms.Select(attrs={"class": "form-control"}),
            "language": forms.Select(attrs={"class": "form-control"}),
            "theme": forms.Select(attrs={"class": "form-control"}),
        }