import importlib
import logging

from django.conf import settings
from django.urls import include, path

from ansible_base.authentication import views
from ansible_base.authentication.apps import AuthenticationConfig
from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugins, get_authenticator_urls
from ansible_base.lib.routers import AssociationResourceRouter

logger = logging.getLogger('ansible_base.authentication.urls')

app_name = AuthenticationConfig.label

list_actions = {'get': 'list', 'post': 'create'}
detail_actions = {'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}
view_only_list = {'get': 'list'}

api_version_urls = []

# Load urls from authenticator plugins
for plugin_name in get_authenticator_plugins():
    plugin_urls = getattr(get_authenticator_urls(plugin_name), 'urls', None)
    if plugin_urls:
        api_version_urls.extend(plugin_urls)
        logger.debug(f"Loaded URLS from {plugin_name}")


authenticator_related_views = {
    'authenticator_maps': (views.AuthenticatorMapViewSet, 'authenticator_map'),
}
try:
    user_viewset_name = settings.ANSIBLE_BASE_USER_VIEWSET
    module_name, junk, class_name = user_viewset_name.rpartition('.')
    module = importlib.import_module(module_name, package=class_name)
    user_viewset_view = getattr(module, class_name)
    authenticator_related_views['users'] = (user_viewset_view, 'users')
except Exception:
    pass

router = AssociationResourceRouter()
router.register('authenticators', views.AuthenticatorViewSet, related_views=authenticator_related_views)
router.register(
    'authenticator_maps',
    views.AuthenticatorMapViewSet,
    related_views={
        'authenticators': (views.AuthenticatorViewSet, 'authenticators'),
    },
)

api_version_urls.extend(
    [
        # Authenticators
        path('', include(router.urls)),
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
