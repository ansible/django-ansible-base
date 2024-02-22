from django.urls import include, path

from ansible_base.lib.routers import AssociationResourceRouter
from ansible_base.activitystream import views

router = AssociationResourceRouter()
router.register(
    'activitystream',
    views.EntryReadOnlyViewSet,
)

api_version_urls = [path('', include((router.urls, 'dab_activitystream'), namespace='activitystream'))]
