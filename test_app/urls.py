from django.contrib import admin
from django.urls import include, path, re_path

from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls
from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from test_app.router import router as test_app_router

urlpatterns = [
    path('api/v1/', include(api_version_urls)),
    path('api/', include(api_urls)),
    path('', include(root_urls)),
    # views specific to test_app
    path('api/v1/', include(test_app_router.urls)),
    # Admin application
    re_path(r"^admin/", admin.site.urls, name="admin"),
    path('api/v1/', include(resource_api_urls)),
]
