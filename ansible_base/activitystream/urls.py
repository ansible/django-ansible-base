from django.urls import include, path

from ansible_base.activitystream import views
from ansible_base.lib.routers import AssociationResourceRouter

router = AssociationResourceRouter()
router.register(
    'activitystream',
    views.EntryReadOnlyViewSet,
    basename='activitystream',
    related_views={
        'changes': (views.FieldChangeReadOnlyViewSet, 'entry'),
    },
)

api_version_urls = [path('', include(router.urls))]
