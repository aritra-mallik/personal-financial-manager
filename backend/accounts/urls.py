from django.urls import path
from . import views
from accounts.views import register, loginpage, logoutpage, dashboard, forgot, homepage

urlpatterns = [
    path('', views.homepage, name='homepage'),
    path('register/', views.register, name='register'),
    path('login/', views.loginpage, name='login'),
    path('logout/', views.logoutpage, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('forgot/', views.forgot, name='forgot'),
    
]
 