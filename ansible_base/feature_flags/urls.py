from django.urls import path

from ansible_base.feature_flags import views
from ansible_base.feature_flags.apps import FeatureFlagsConfig

app_name = FeatureFlagsConfig.label

api_version_urls = [
    path('feature_flags_definition', views.FeatureFlagsListView.as_view(), name='featureflags-list'),
]
api_urls = []
root_urls = []
