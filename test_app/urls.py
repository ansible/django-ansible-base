from django.contrib import admin
from django.urls import include, path, re_path

from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls

urlpatterns = [
    path('api/v1/', include(api_version_urls)),
    path('api/', include(api_urls)),
    path('', include(root_urls)),
    # Admin application
    re_path(r"^admin/", admin.site.urls, name="admin"),
]
