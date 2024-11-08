from ansible_base.django_template import views
from ansible_base.django_template.views.api.v1.user import OrganizationRelatedUserViewSet, TeamRelatedUserViewSet
from ansible_base.lib.routers import AssociationResourceRouter
from ansible_base.lib.utils.auth import get_organization_model, get_team_model

router = AssociationResourceRouter()
router.register(
    r'users',
    views.UserViewSet,
    related_views={},
)
if get_organization_model(return_none_on_error=True) is not None:
    related_views = {
        'users': (OrganizationRelatedUserViewSet, 'users'),
        'admins': (OrganizationRelatedUserViewSet, 'admins'),
    }
    if get_team_model(return_none_on_error=True) is not None:
        related_views['teams'] = (views.TeamViewSet, 'teams')
    router.register(
        r'organizations',
        views.OrganizationViewSet,
        related_views=related_views,
        basename="organization",
    )

if get_team_model(return_none_on_error=True) is not None:
    router.register(
        r'teams',
        views.TeamViewSet,
        related_views={
            'users': (TeamRelatedUserViewSet, 'users'),
            'admins': (TeamRelatedUserViewSet, 'admins'),
        },
        basename='team',
)
