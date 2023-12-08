import logging

from django.urls import include, path, re_path
from rest_framework import routers

from ansible_base import views

logger = logging.getLogger('ansible_base.resource-urls')

service_router = routers.SimpleRouter()

service_router.register(r'resources', views.ResourceViewSet)
service_router.register(r'resource-types', views.ResourceTypeViewSet)
service_router.register(r'transactions', views.TransactionViewSet)

services = [path('metadata/', views.ServiceMetadataView.as_view()), path('', include(service_router.urls))]

resource_api_urls = [
    path('services/self/', include(services)),
    re_path(r'services/(?P<service_id>[0-9a-zA-Z\-]+)/', include(services)),
]
