from django.urls import include, path

from ansible_base.features.apps import FeaturesConfig
from ansible_base.features.views import FeatureViewSet
from ansible_base.lib.routers import AssociationResourceRouter

app_name = FeaturesConfig.label


router = AssociationResourceRouter()
router.register(
    'features',
    FeatureViewSet,
    related_views={},
)

api_version_urls = [
    path('', include(router.urls)),
]
api_urls = []
root_urls = []
