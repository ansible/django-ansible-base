from rest_framework.routers import SimpleRouter

from ansible_base.lib.routers import AssociationResourceRouter
from test_app import views

router = SimpleRouter()
# using an intentionally unpredictable basename
router.register(r'encrypted_models', views.EncryptionModelViewSet, basename='encryption_test_model')
# this uses standard registration
router.register(r'related_fields_test_models', views.RelatedFieldsTestModelViewSet)
# intentionally not registering ResourceMigrationTestModel to test lack of URLs

associative_router = AssociationResourceRouter()
associative_router.register(
    r'related_model',
    views.RelatedFieldsTestModelViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'more_teams'),
        'user': (views.UserViewSet, 'users'),
    },
    basename='related_fields_test_model',
)

associative_router.register(
    r'organizations',
    views.OrganizationViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
    },
    basename='organization',
)

associative_router.register(
    r'teams',
    views.TeamViewSet,
    basename='team',
)

associative_router.register(r'users', views.UserViewSet, basename='user')
