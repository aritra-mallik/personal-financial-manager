from django.shortcuts import render
from django.contrib.auth.decorators import login_required

# Create your views here.

@login_required
def privacy(request):
    return render(request, 'core/privacy.html')

@login_required
def terms(request):
    return render(request, 'core/terms.html')

""" @login_required
def settings(request):
    return render(request, 'core/settings.html') """

# core/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import UserPreference
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User

@login_required
def update_preferences(request):
    if request.method == 'POST' and request.user.is_authenticated:
        prefs, _ = UserPreference.objects.get_or_create(user=request.user)
        prefs.theme = request.POST.get('theme', prefs.theme)
        prefs.currency = request.POST.get('currency', prefs.currency)
        prefs.language = request.POST.get('language', prefs.language)
        prefs.save()
        messages.success(request, "Preferences updated successfully!")
    return redirect(request.META.get('HTTP_REFERER', '/'))

@login_required
def settings_view(request):
    prefs, _ = UserPreference.objects.get_or_create(user=request.user)

    if request.method == "POST":
        # Handle General Settings
        if "currency" in request.POST:
            prefs.currency = request.POST.get("currency")
            prefs.language = request.POST.get("language")
            prefs.theme = request.POST.get("theme")
            prefs.save()
            messages.success(request, "✅ Preferences saved successfully!")

        # Handle Password Change
        if "current_password" in request.POST:
            current = request.POST.get("current_password")
            new = request.POST.get("new_password")
            confirm = request.POST.get("confirm_password")

            if not current or not new or not confirm:
                messages.error(request, "⚠️ Please fill all password fields!")
            elif not request.user.check_password(current):
                messages.error(request, "❌ Current password is incorrect!")
            elif new != confirm:
                messages.error(request, "❌ New passwords do not match!")
            else:
                request.user.set_password(new)
                request.user.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "🔒 Password updated successfully!")

        return redirect("settings_view")

    return render(request, "core/settings.html", {"prefs": prefs})
