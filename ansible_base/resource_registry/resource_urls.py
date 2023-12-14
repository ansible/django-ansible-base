import logging

from django.urls import include, path, re_path
from rest_framework import routers

from ansible_base import views

logger = logging.getLogger('ansible_base.resource-urls')

service_router = routers.SimpleRouter()

service_router.register(r'resources', views.ResourceViewSet)
service_router.register(r'resource-types', views.ResourceTypeViewSet)
service_router.register(r'transactions', views.TransactionViewSet)

service = [path('metadata/', views.ServiceMetadataView.as_view()), path('', include(service_router.urls))]

resource_api_urls = [
    path('service/', include(service)),
]
