import logging

from django.urls import path, re_path

from ansible_base import views
from ansible_base.authenticator_plugins.utils import get_authenticator_plugins, get_authenticator_urls
from ansible_base.utils.settings import feature_enabled

logger = logging.getLogger('ansible_base.urls')

list_actions = {'get': 'list', 'post': 'create'}
detail_actions = {'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}
view_only_list = {'get': 'list'}

urls = []

if feature_enabled('AUTHENTICATION'):
    # Load urls from authenticator plugins
    for plugin_name in get_authenticator_plugins():
        plugin_urls = getattr(get_authenticator_urls(plugin_name), 'urls', None)
        if plugin_urls:
            urls.extend(plugin_urls)
            logger.debug(f"Loaded URLS from {plugin_name}")

    urls.extend(
        [
            # Authenticators
            path('authenticators/', views.AuthenticatorViewSet.as_view(list_actions), name='authenticator-list'),
            re_path(r'authenticators/(?P<pk>[0-9]+)/$', views.AuthenticatorViewSet.as_view(detail_actions), name='authenticator-detail'),
            re_path(
                r'authenticators/(?P<pk>[0-9]+)/authenticator_maps/$',
                views.AuthenticatorAuthenticatorMapViewSet.as_view(view_only_list),
                name='authenticator-authenticator-map-list',
            ),
            # Maps
            path('authenticator_maps/', views.AuthenticatorMapViewSet.as_view(list_actions), name='authenticator_map-list'),
            re_path(r'authenticator_maps/(?P<pk>[0-9]+)/$', views.AuthenticatorMapViewSet.as_view(detail_actions), name='authenticator_map-detail'),
            # Plugin List
            path('authenticator_plugins/', views.AuthenticatorPluginView.as_view(), name='authenticator_plugin-view'),
            # Trigger definition
            path('trigger_definition/', views.TriggerDefinitionView.as_view(), name='trigger_definition-view'),
            path('ui_auth/', views.UIAuth.as_view(), name='ui_auth-view'),
        ]
    )

if feature_enabled('OAUTH2_SERVER'):
    from oauth2_provider import views as oauth_views

    from ansible_base.views import oauth2_provider as oauth2_providers_views

    oauth2_urls = [
        re_path(r'^$', oauth2_providers_views.ApiOAuthAuthorizationRootView.as_view(), name='oauth_authorization_root_view'),
        re_path(r"^authorize/$", oauth_views.AuthorizationView.as_view(), name="authorize"),
        re_path(r"^token/$", oauth2_providers_views.TokenView.as_view(), name="token"),
        re_path(r"^revoke_token/$", oauth_views.RevokeTokenView.as_view(), name="revoke-token"),
    ]

    urls.extend(
        [
            re_path(r'^applications/', oauth2_providers_views.OAuth2ApplicationViewSet.as_view(list_actions), name='o_auth2_application_list'),
            re_path(
                r'^applications/(?P<pk>[0-9]+)/$', oauth2_providers_views.OAuth2ApplicationViewSet.as_view(detail_actions), name='o_auth2_application_detail'
            ),
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
            re_path(r'^tokens/', oauth2_providers_views.OAuth2TokenViewSet.as_view(list_actions), name='o_auth2_token_list'),
            re_path(r'^tokens/(?P<pk>[0-9]+)/$', oauth2_providers_views.OAuth2TokenViewSet.as_view(detail_actions), name='o_auth2_token_detail'),
            # re_path(
            #     r'^tokens/(?P<pk>[0-9]+)/activity_stream/$',
            #     oauth2_providers_views.OAuth2TokenActivityStreamList.as_view(),
            #     name='o_auth2_token_activity_stream_list'
            # ),
        ]
    )
