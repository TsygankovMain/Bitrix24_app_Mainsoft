from django.contrib import admin
from django.urls import path, include

from config import config

urlpatterns = [
    path('', include('main.urls')),
]

if config.django_admin_enabled:
    urlpatterns = [path('api/admin/', admin.site.urls)] + urlpatterns
