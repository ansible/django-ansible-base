from django.contrib import admin
from django.urls import include, path, re_path

urlpatterns = [
    re_path(r'api/v1/', include('ansible_base.urls')),
    # Social auth
    path('api/social/', include('social_django.urls', namespace='social')),
    # Admin application
    re_path(r"^admin/", admin.site.urls, name="admin"),
]
