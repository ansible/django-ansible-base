# Open API and Swagger documentation

django-ansible-base uses django-spectacular to auto-generate both Open API and Swagger documentation of the API.

To enable this first edit your settings and add:
```
SPECTACULAR_SETTINGS = {
    'TITLE': 'AAP <Service Name> API',
    'DESCRIPTION': 'AAP <Service Name> API',
    'VERSION': 'v<Service Version>',
    'SCHEMA_PATH_PREFIX': '/api/<path as required>/v<Service Version>/',
}
```

Then add the following to your urls.py:
```
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    ...
    path('api/v1/docs/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/docs/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),   
    ...
]
```
