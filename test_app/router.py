from ansible_base.lib.routers import AssociationResourceRouter
from ansible_base.oauth2_provider import views as oauth2_provider_views
from ansible_base.rbac.api import views as rbac_views
from test_app import views

router = AssociationResourceRouter()
# using an intentionally unpredictable basename
router.register(r'encrypted_models', views.EncryptionModelViewSet, basename='encryption_test_model')

# intentionally not registering ResourceMigrationTestModel to test lack of URLs


# Here, we demonstrate how to turn on or off filtering of related endpoints
# viewsets of models with roles filter to what is visable by requesting user
# in the filter_queryset method, but in some endpoints we show all users
class RelatedUserViewSet(views.UserViewSet):
    def filter_queryset(self, qs):
        return self.apply_optimizations(qs)


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
        'members': (RelatedUserViewSet, 'users'),
        'admins': (RelatedUserViewSet, 'admins'),
        'teams': (views.TeamViewSet, 'teams'),
        'inventories': (views.InventoryViewSet, 'inventories'),
        'namespaces': (views.NamespaceViewSet, 'namespaces'),
        'cows': (views.CowViewSet, 'cows'),
        'uuidmodels': (views.UUIDModelViewSet, 'uuidmodels'),
        'parentnames': (views.ParentNameViewSet, 'parentnames'),
        'positionmodels': (views.PositionModelViewSet, 'positionmodels'),
        'weirdperms': (views.WeirdPermViewSet, 'weirdperms'),
    },
)

router.register(
    r'teams',
    views.TeamViewSet,
    related_views={
        'members': (RelatedUserViewSet, 'users'),
        'admins': (RelatedUserViewSet, 'admins'),
        'parents': (views.TeamViewSet, 'team_parents'),
        'role_assignments': (rbac_views.RoleTeamAssignmentViewSet, 'role_assignments'),
    },
)

router.register(
    r'users',
    views.UserViewSet,
    related_views={
        'organizations': (views.OrganizationViewSet, 'organizations'),
        'teams': (views.TeamViewSet, 'teams'),
        'tokens': (oauth2_provider_views.OAuth2TokenViewSet, 'access_tokens'),
        'applications': (oauth2_provider_views.OAuth2ApplicationViewSet, 'applications'),
    },
    basename='user',
)
router.register(r'inventories', views.InventoryViewSet)
router.register(r'instance_groups', views.InstanceGroupViewSet)
router.register(r'cows', views.CowViewSet)
router.register(r'uuidmodels', views.UUIDModelViewSet)
router.register(r'cities', views.CityViewSet)
router.register(r'animals', views.AnimalViewSet)
router.register(r'namespaces', views.NamespaceViewSet, related_views={'collections': (views.CollectionImportViewSet, 'collections')})
router.register(r'collections', views.CollectionImportViewSet)
