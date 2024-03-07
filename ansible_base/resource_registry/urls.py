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
    path('validate-local-account/', views.ValidateLocalUserView.as_view(), name="validate-local-account"),
    path('', include(service_router.urls)),
    path('', views.ServiceIndexRootView.as_view(), name='service-index-root'),
]

urlpatterns = [
    path('service-index/', include(service)),
]
