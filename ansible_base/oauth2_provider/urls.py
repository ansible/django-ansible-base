from django.urls import include, path, re_path
from flags.urls import flagged_re_path
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

FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED = 'FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED'

oauth_urls = [
    re_path(r'^$', oauth2_provider_views.ApiOAuthAuthorizationRootView.as_view(), name='oauth_authorization_root_view'),
    re_path(r"^authorize/$", oauth_views.AuthorizationView.as_view(), name="authorize"),
    re_path(r"^token/$", oauth2_provider_views.TokenView.as_view(), name="token"),
    re_path(r"^revoke_token/$", oauth_views.RevokeTokenView.as_view(), name="revoke-token"),
    # OIDC endpoints - flag is checked at request time, returns 404 when disabled
    flagged_re_path(
        FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED,
        r"^\.well-known/openid-configuration$",
        oauth_views.ConnectDiscoveryInfoView.as_view(),
        name="oidc-connect-discovery-info",
    ),
    flagged_re_path(FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED, r"^\.well-known/jwks\.json$", oauth_views.JwksInfoView.as_view(), name="jwks-info"),
    flagged_re_path(FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED, r"^userinfo$", oauth_views.UserInfoView.as_view(), name="user-info"),
]


root_urls = [
    re_path(r"^o/", include((oauth_urls, 'oauth2_provider'))),
]
