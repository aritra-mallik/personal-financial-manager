from django.shortcuts import render, HttpResponse, redirect
from django.contrib import messages
from django.contrib.auth import login , logout, authenticate  



# Create your views here.
from .forms import CreateUserForm

def homepage(request):
    context = {}
    return render(request, 'accounts/homepage.html', context)


def register(request):
    form = CreateUserForm()
    if request.method == 'POST':
        form = CreateUserForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Account created successfully! You can now log in.")
            return redirect('login') 
    context= {'form': form}
    return render(request, 'accounts/register.html', context)

def loginpage(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "Login successful!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    context= {}
    return render(request, 'accounts/login.html', context)

def logoutpage(request):
    logout(request)
    return redirect('login') 


def dashboard(request):
    context={}
    return render(request, 'accounts/dashboard.html', context)

