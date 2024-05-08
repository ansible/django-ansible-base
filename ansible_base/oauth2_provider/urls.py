from django.urls import include, path, re_path
from oauth2_provider import views as oauth_views

from ansible_base.lib.routers import AssociationResourceRouter
from ansible_base.oauth2_provider import views as oauth2_provider_views
from ansible_base.oauth2_provider.apps import Oauth2ProviderConfig

app_name = Oauth2ProviderConfig.label

router = AssociationResourceRouter()

router.register(
    r'applications',
    oauth2_provider_views.OAuth2ApplicationViewSet,
    basename='application',
    related_views={
        'tokens': (oauth2_provider_views.OAuth2TokenViewSet, 'access_tokens'),
    },
)

router.register(
    r'tokens',
    oauth2_provider_views.OAuth2TokenViewSet,
    basename='token',
)

api_version_urls = [
    path('', include(router.urls)),
]

root_urls = [
    re_path(r'^o/$', oauth2_provider_views.ApiOAuthAuthorizationRootView.as_view(), name='oauth_authorization_root_view'),
    re_path(r"^o/authorize/$", oauth_views.AuthorizationView.as_view(), name="authorize"),
    re_path(r"^o/token/$", oauth2_provider_views.TokenView.as_view(), name="token"),
    re_path(r"^o/revoke_token/$", oauth_views.RevokeTokenView.as_view(), name="revoke-token"),
]
