from django.urls import include, path, re_path

from ansible_base.django_template import views
from ansible_base.django_template.router import router
from ansible_base.lib.utils.auth import get_organization_model, get_team_model

root_urls = []

api_urls = [
    path('v1/', views.V1RootView.as_view(), name='api_app_v1_root_view'),
]

api_version_urls = [
    path('', include(router.urls)),
    # Default views from ansible_base
    path(
        'login/',
        views.LoggedLoginView.as_view(template_name='rest_framework/login.html', extra_context={'inside_login_context': True}),
        name='login',
    ),
    path('logout/', views.LoggedLogoutView.as_view(next_page='/api/', redirect_field_name='next'), name='logout'),
    path('me/', views.MeViewSet.as_view({'get': 'list'}), name='me-list'),
    path('ping/', views.PingView.as_view(), name='ping-view'),
    path('session/', views.SessionView.as_view(), name='session-view'),
]

if get_team_model(return_none_on_error=True) is not None:
    api_version_urls.append(re_path('users/(?P<pk>[0-9]+)/teams/', views.UserTeamViewSet.as_view({'get': 'list'}), name='user-teams-list'))
if get_organization_model(return_none_on_error=True) is not None:
    api_version_urls.append(re_path('users/(?P<pk>[0-9]+)/organizations/', views.UserOrganizationViewSet.as_view({'get': 'list'}), name='user-organizations-list'))
