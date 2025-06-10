from django.urls import path

from ansible_base.feature_flags import views
from ansible_base.feature_flags.apps import FeatureFlagsConfig

app_name = FeatureFlagsConfig.label

api_version_urls = [
    path('feature_flags_state/', views.FeatureFlagsStateListView.as_view(), name='feature-flags-state-list'),
]
api_urls = []
root_urls = []
