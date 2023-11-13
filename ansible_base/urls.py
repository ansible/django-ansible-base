from django.urls import path, re_path

from ansible_base import views

list_actions = {'get': 'list', 'post': 'create'}
detail_actions = {'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}
view_only_list = {'get': 'list'}

urls = [
    # Authenticators
    path('authenticators/', views.AuthenticatorViewSet.as_view(list_actions), name='authenticator-list'),
    re_path(r'authenticators/(?P<pk>[0-9]+)/$', views.AuthenticatorViewSet.as_view(detail_actions), name='authenticator-detail'),
    re_path(
        r'authenticators/(?P<pk>[0-9]+)/authenticator_maps/$',
        views.AuthenticatorAuthenticatorMapViewSet.as_view(view_only_list),
        name='authenticator-authenticator-map',
    ),
    # Maps
    path('authenticator_maps/', views.AuthenticatorMapViewSet.as_view(list_actions), name='authenticator_map-list'),
    re_path(r'authenticator_maps/(?P<pk>[0-9]+)/$', views.AuthenticatorMapViewSet.as_view(detail_actions), name='authenticator_map-detail'),
    # Plugin List
    path('authenticator_plugins/', views.AuthenticatorPluginView.as_view(), name='authenticator_plugin-view'),
    # Trigger definition
    path('trigger_definition/', views.TriggerDefinitionView.as_view(), name='trigger_definition-view'),
    path('ui_auth/', views.UIAuth.as_view(), name='ui_auth-view'),
    # Ansible Resource
    path('ansible-resources/', views.ResourceViewSet.as_view(view_only_list), name='resource-list'),
    re_path(r'ansible-resources/(?P<ansible_id>[0-9a-zA-Z\-]+)/$', views.ResourceViewSet.as_view({'get': 'retrieve'}), name='resource-detail'),
    re_path(
        r'ansible-resources/(?P<ansible_id>[0-9a-zA-Z\-]+)/permissions/$', views.ResourceViewSet.as_view({'get': 'permissions'}), name='resource-permission'
    ),
    path('ansible-resource-types/', views.ResourceTypeViewSet.as_view(view_only_list), name='resourcetype-list'),
    re_path(r'ansible-resource-types/(?P<pk>[0-9a-zA-Z\-]+)/$', views.ResourceTypeViewSet.as_view({'get': 'retrieve'}), name='resourcetype-detail'),
]
