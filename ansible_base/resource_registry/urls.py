import logging

from django.urls import include, path
from rest_framework import routers

from ansible_base.resource_registry import views

logger = logging.getLogger('ansible_base.resource-urls')

service_router = routers.SimpleRouter()

service_router.register(r'resources', views.ResourceViewSet)
service_router.register(r'resource-types', views.ResourceTypeViewSet)

service = [path('metadata/', views.ServiceMetadataView.as_view(), name="service-metadata"), path('', include(service_router.urls))]

urlpatterns = [
    path('service-index/', include(service)),
]
