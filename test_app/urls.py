from django.contrib import admin
from django.urls import include, path, re_path

from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls

from test_app.views import router as user_router


urlpatterns = [
    path('api/v1/', include(api_version_urls)),
    path('api/v1/', include(user_router.urls)),
    path('api/', include(api_urls)),
    path('', include(root_urls)),
    # Admin application
    re_path(r"^admin/", admin.site.urls, name="admin"),
]
