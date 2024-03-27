#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from django.contrib import admin
from django.urls import include, path, re_path

from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls
from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from test_app import views
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
    path('api/v1/', views.api_root),
    path('login/', include('rest_framework.urls')),
    path("__debug__/", include("debug_toolbar.urls")),
]
