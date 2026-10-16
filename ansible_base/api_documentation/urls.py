from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from ansible_base.api_documentation.apps import ApiDocumentationConfig
from ansible_base.api_documentation.views import DocsRootView

app_name = ApiDocumentationConfig.label
api_version_urls = [
    path('docs/', DocsRootView.as_view(), name='docs-root'),
    path('docs/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('docs/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('docs/schema/', SpectacularAPIView.as_view(), name='schema'),
]
