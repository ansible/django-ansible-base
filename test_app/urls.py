from django.contrib import admin
from django.urls import include, path, re_path

from ansible_base.authentication.views.ui_auth import UIAuth
from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls
from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from test_app import views
from test_app.router import router as test_app_router

urlpatterns = [
    path('', views.index_view),
    path('api/v1/ui_auth/', UIAuth.as_view(), name='ui-auth-view'),
    path('api/v1/', include(api_version_urls)),
    path('api/', include(api_urls)),
    path('', include(root_urls)),
    # views specific to test_app
    path('api/v1/', include(test_app_router.urls)),
    # Admin application
    re_path(r"^admin/", admin.site.urls, name="admin"),
    path('api/v1/', include(resource_api_urls)),
    path('api/v1/', views.api_root),
    path('login/', include('rest_framework.urls')),
    path("__debug__/", include("debug_toolbar.urls")),
]
