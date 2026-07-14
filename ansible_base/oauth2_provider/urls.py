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

oauth_urls = [
    re_path(r'^$', oauth2_provider_views.ApiOAuthAuthorizationRootView.as_view(), name='oauth_authorization_root_view'),
    re_path(r"^authorize/$", oauth2_provider_views.AuthorizationView.as_view(), name="authorize"),
    re_path(r"^token/$", oauth2_provider_views.TokenView.as_view(), name="token"),
    re_path(r"^revoke_token/$", oauth_views.RevokeTokenView.as_view(), name="revoke-token"),
    # OIDC endpoints
    # URL patterns below must match installed django-oauth-toolkit version, otherwise discovery fails
    # See https://github.com/django-oauth/django-oauth-toolkit/blob/2.3.0/oauth2_provider/urls.py#L35
    re_path(r"^\.well-known/openid-configuration/$", oauth2_provider_views.DiscoveryInfoView.as_view(), name="oidc-connect-discovery-info"),
    re_path(r"^\.well-known/jwks\.json$", oauth_views.JwksInfoView.as_view(), name="jwks-info"),
    re_path(r"^userinfo/$", oauth_views.UserInfoView.as_view(), name="user-info"),
    re_path(r"^logout/$", oauth_views.RPInitiatedLogoutView.as_view(), name="rp-initiated-logout"),
]


root_urls = [
    # Catch-all for unhandled /.well-known/ paths. Without this, Django falls
    # through to the UI root and returns the login page HTML instead of a 404.
    # Registered endpoints (e.g. /o/.well-known/openid-configuration/) are
    # matched first under the /o/ prefix, so they are unaffected.
    re_path(r"^\.well-known/", oauth2_provider_views.NotFoundView.as_view()),
    re_path(r"^o/", include((oauth_urls, 'oauth2_provider'))),
]
