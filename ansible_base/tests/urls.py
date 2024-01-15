from django.urls import include, path, re_path
from django.contrib import admin

from ansible_base.urls import urls as base_urls

urlpatterns = [
    re_path(r'api/v1/', include(base_urls)),
    # Social auth
    path('api/social/', include('social_django.urls', namespace='social')),
    re_path(r"^admin/", admin.site.urls, name="admin"),
]
