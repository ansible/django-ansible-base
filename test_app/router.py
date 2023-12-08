from ansible_base.lib.routers import AssociationResourceRouter
from test_app import views

router = AssociationResourceRouter()
# using an intentionally unpredictable basename
router.register(r'encrypted_models', views.EncryptionModelViewSet, basename='encryption_test_model')

# intentionally not registering ResourceMigrationTestModel to test lack of URLs

router.register(
    r'related_fields_test_models',
    views.RelatedFieldsTestModelViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'more_teams'),
        'user': (views.UserViewSet, 'users'),
    },
    basename='related_fields_test_model',
)

router.register(
    r'organizations',
    views.OrganizationViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
    },
    basename='organization',
)

router.register(
    r'teams',
    views.TeamViewSet,
    basename='team',
)

router.register(
    r'users',
    views.UserViewSet,
    related_views={
        'organizations': (views.OrganizationViewSet, 'organizations'),
        'teams': (views.TeamViewSet, 'teams'),
    },
    basename='user',
)
router.register(r'inventories', views.InventoryViewSet, basename='inventory')
router.register(r'instance_groups', views.InstanceGroupViewSet, basename='instancegroup')
router.register(r'cows', views.CowViewSet, basename='cow')
router.register(r'uuidmodels', views.UUIDModelViewSet, basename='uuidmodel')
