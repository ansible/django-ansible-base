from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from ansible_base.authentication.views.ui_auth import UIAuth
from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls
from ansible_base.rbac.service_api.urls import rbac_service_urls
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
    path('api/v1/', include(rbac_service_urls)),
    path('api/v1/', views.api_root),
    path('api/v1/otel/traces/', views.otel_traces, name='otel-traces'),
    path('api/v1/otel/logs/', views.otel_logs, name='otel-logs'),
    path('api/v1/otel/observability-headers-start/', views.observability_headers_start, name='otel-observability-headers-start'),
    path('api/v1/otel/observability-headers-echo/', views.observability_headers_echo, name='otel-observability-headers-echo'),
    path('api/v1/timeout_view/', views.timeout_view, name='test-timeout-view'),
    # Profile stories
    path('api/v1/profile-stories/', views.profile_stories_root, name='profile-stories'),
    path('api/v1/profile-stories/org-delete/', views.org_delete_root, name='profile-stories-org-delete'),
    path('api/v1/profile-stories/org-delete/populate/', views.org_delete_populate, name='org-delete-populate'),
    path('api/v1/profile-stories/org-delete/bare/', views.org_delete_bare, name='org-delete-bare'),
    path('api/v1/profile-stories/org-delete/deferred/', views.org_delete_deferred, name='org-delete-deferred'),
    path('api/v1/profile-stories/org-delete/optimized/', views.org_delete_all_optimized, name='org-delete-optimized'),
    path('login/', include('rest_framework.urls')),
    path("__debug__/", include("debug_toolbar.urls")),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
