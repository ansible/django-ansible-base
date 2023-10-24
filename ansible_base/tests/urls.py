from django.urls import include, re_path, path

from ansible_base.urls import urls as base_urls


urlpatterns = [
    re_path(r'api/gateway/v1/', include(base_urls)),
    # Social auth
    path('api/gateway/social/', include('social_django.urls', namespace='social')),
]
