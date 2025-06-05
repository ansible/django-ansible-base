from django.urls import include, path

from ansible_base.feature_flags import views
from ansible_base.feature_flags.apps import FeatureFlagsConfig
from ansible_base.lib.routers import AssociationResourceRouter

app_name = FeatureFlagsConfig.label

router = AssociationResourceRouter()

router.register(r'feature_flags/states', views.FeatureFlagsStatesView, basename='aap_flags_states')
# TODO: Remove once all components are migrated to new endpoints.
api_version_urls = [path('feature_flags_state/', views.OldFeatureFlagsStateListView.as_view(), name='feature-flags-state-list'), path('', include(router.urls))]

api_urls = []
root_urls = []
