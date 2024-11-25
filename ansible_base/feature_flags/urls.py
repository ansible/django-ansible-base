from django.urls import path, re_path

from ansible_base.feature_flags import views
from ansible_base.feature_flags.apps import FeatureFlagsConfig

app_name = FeatureFlagsConfig.label

api_version_urls = [
    path('flags/', views.FeatureFlagsListView.as_view(), name='featureflags-list'),
    re_path(r'flags/(?P<category_slug>[a-zA-Z0-9_]+)/$', views.FeatureFlagDetailView.as_view(), name='featureflags-detail'),
]
api_urls = []
root_urls = []
