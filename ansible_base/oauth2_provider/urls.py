from django.urls import include, path, re_path
from oauth2_provider import views as oauth_views

from ansible_base.lib.routers import AssociationResourceRouter
from ansible_base.oauth2_provider import views as oauth2_providers_views

router = AssociationResourceRouter()

router.register(
    r'applications',
    oauth2_providers_views.OAuth2ApplicationViewSet,
)

router.register(r'tokens', oauth2_providers_views.OAuth2TokenViewSet)

api_version_urls = [
    path('', include(router.urls)),
]

# re_path(
#     r'^applications/(?P<pk>[0-9]+)/tokens/$',
#     oauth2_providers_views.ApplicationOAuth2TokenList.as_view(),
#     name='o_auth2_application_token_list'
# ),
# re_path(
#     r'^applications/(?P<pk>[0-9]+)/activity_stream/$',
#     oauth2_providers_views.OAuth2ApplicationActivityStreamList.as_view(),
#     name='o_auth2_application_activity_stream_list'
# ),
# re_path(
#     r'^tokens/(?P<pk>[0-9]+)/activity_stream/$',
#     oauth2_providers_views.OAuth2TokenActivityStreamList.as_view(),
#     name='o_auth2_token_activity_stream_list'
# ),

root_urls = [
    re_path(r'^o/$', oauth2_providers_views.ApiOAuthAuthorizationRootView.as_view(), name='oauth_authorization_root_view'),
    re_path(r"^o/authorize/$", oauth_views.AuthorizationView.as_view(), name="authorize"),
    re_path(r"^o/token/$", oauth2_providers_views.TokenView.as_view(), name="token"),
    re_path(r"^o/revoke_token/$", oauth_views.RevokeTokenView.as_view(), name="revoke-token"),
]
