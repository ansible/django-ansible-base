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

import logging

from django.urls import include, path
from rest_framework import routers

from ansible_base.resource_registry import views

logger = logging.getLogger('ansible_base.resource-urls')

service_router = routers.SimpleRouter()

service_router.register(r'resources', views.ResourceViewSet)
service_router.register(r'resource-types', views.ResourceTypeViewSet)

service = [
    path('metadata/', views.ServiceMetadataView.as_view(), name="service-metadata"),
    path('', include(service_router.urls)),
    path('', views.ServiceIndexRootView.as_view(), name='service-index-root'),
]

urlpatterns = [
    path('service-index/', include(service)),
]
