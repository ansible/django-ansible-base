from django.urls import path

from ansible_base.feature_flags import views
from ansible_base.feature_flags.apps import FeatureFlagsConfig

app_name = FeatureFlagsConfig.label

api_version_urls = [
    path('flags/', views.FeatureFlagView.as_view({'get': 'list'}), name='feature_flag-view'),
]
api_urls = []
root_urls = []
