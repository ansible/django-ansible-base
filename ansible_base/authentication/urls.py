import logging

from django.urls import include, path, re_path

from ansible_base.authentication import views
from ansible_base.authentication.routers import authentication_router
from ansible_base.authentication.apps import AuthenticationConfig
from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugins, get_authenticator_urls

logger = logging.getLogger('ansible_base.authentication.urls')

app_name = AuthenticationConfig.label

view_only_list = {'get': 'list'}

api_version_urls = []

# Load urls from authenticator plugins
for plugin_name in get_authenticator_plugins():
    plugin_urls = getattr(get_authenticator_urls(plugin_name), 'urls', None)
    if plugin_urls:
        api_version_urls.extend(plugin_urls)
        logger.debug(f"Loaded URLS from {plugin_name}")

api_version_urls.extend(
    [
        # Authenticators and Maps
        path('', include(authentication_router.urls)),
        re_path(
            r'authenticators/(?P<pk>[0-9]+)/authenticator_maps/$',
            views.AuthenticatorAuthenticatorMapViewSet.as_view(view_only_list),
            name='authenticator-authenticator-map-list',
        ),
        # Plugin List
        path('authenticator_plugins/', views.AuthenticatorPluginView.as_view(), name='authenticator_plugin-view'),
        # Trigger definition
        path('trigger_definition/', views.TriggerDefinitionView.as_view(), name='trigger_definition-view'),
        path('ui_auth/', views.UIAuth.as_view(), name='ui_auth-view'),
    ]
)


api_urls = [
    path('social/', include('social_django.urls', namespace='social')),
]
