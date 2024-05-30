import pytest
from django.test.utils import override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.reverse import reverse

from ansible_base.authentication.utils.claims import ReconcileUser
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_ROLES=False)
def test_custom_role_rules_do_not_apply_to_managed_roles():
    RoleDefinition.objects.create_from_permissions(
        permissions=[
            permission_registry.team_permission,
            f'view_{permission_registry.team_model._meta.model_name}',
            'view_organization',
            'change_organization',
        ],
        name='Organization Admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        managed=True,
    )


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_ROLES=False)
def test_role_definition_enablement_validation_in_api(admin_api_client):
    url = reverse('roledefinition-list')
    r = admin_api_client.post(url, data={'name': 'foo', 'permissions': ['view_inventory'], 'content_type': 'aap.inventory'})
    assert r.status_code == 400, r.data
    assert 'Creating custom roles is disabled' in str(r.data)


@pytest.mark.django_db
class TestProhibitedAssignments:
    @override_settings(ANSIBLE_BASE_ALLOW_TEAM_PARENTS=False)
    def test_team_team_assignment(self, member_rd, organization):
        teamA = permission_registry.team_model.objects.create(name='teamA', organization=organization)
        teamB = permission_registry.team_model.objects.create(name='teamB', organization=organization)
        with pytest.raises(ValidationError) as exc:
            member_rd.give_permission(teamA, teamB)
        assert 'Assigning team permissions to other teams is not allowed' in str(exc)

    @override_settings(ANSIBLE_BASE_ALLOW_TEAM_ORG_PERMS=False)
    def test_team_org_assignment(self, organization):
        team = permission_registry.team_model.objects.create(name='example-team', organization=organization)
        view_rd = RoleDefinition.objects.create_from_permissions(
            permissions=['view_organization'], name='view-org', content_type=permission_registry.content_type_model.objects.get_for_model(Organization)
        )
        with pytest.raises(ValidationError) as exc:
            view_rd.give_permission(team, organization)
        assert 'Assigning organization permissions to teams is not allowed' in str(exc)

    @override_settings(ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN=False)
    def test_team_org_member_assignment(self, org_team_member_rd, organization):
        team = permission_registry.team_model.objects.create(name='example-team', organization=organization)
        with pytest.raises(ValidationError) as exc:
            org_team_member_rd.give_permission(team, organization)
        assert 'Assigning organization permissions that manage other teams is not allowed' in str(exc)

    @override_settings(ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES=False)
    def test_system_roles_disabled_only_for_teams(self, rando, team):
        "This is intended to be used in AWX, as the legacy system auditor role is only for users"
        rd = RoleDefinition.objects.create_from_permissions(name='system-inventory-viewer', permissions=['view_inventory'], content_type=None)
        # Global roles are enabled for users
        rd.give_global_permission(rando)
        with pytest.raises(ValidationError) as exc:
            rd.give_global_permission(team)
        assert 'Global roles are not enabled for teams' in str(exc)


@pytest.mark.django_db
class TestProhibitedRoleDefinitions:
    @override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_ROLES=False)
    def test_all_custom_roles_disabled(self):
        with pytest.raises(ValidationError) as exc:
            RoleDefinition.objects.create_from_permissions(
                name='anything', permissions=['view_inventory'], content_type=permission_registry.content_type_model.objects.get_for_model(Inventory)
            )
        assert 'Creating custom roles is disabled' in str(exc)

    @override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES=False)
    def test_custom_team_roles_disabled(self):
        RoleDefinition.objects.create_from_permissions(
            name='resource-stuff', permissions=['view_inventory'], content_type=permission_registry.content_type_model.objects.get_for_model(Inventory)
        )
        with pytest.raises(ValidationError) as exc:
            RoleDefinition.objects.create_from_permissions(
                name=type(RoleDefinition.objects.managed).team_member.role_name,
                permissions=['member_team', 'view_team'],
                content_type=permission_registry.content_type_model.objects.get_for_model(permission_registry.team_model),
            )
        assert 'Creating custom roles for teams is disabled' in str(exc)
        with pytest.raises(ValidationError) as exc:
            RoleDefinition.objects.create_from_permissions(
                name='org-team-member',
                permissions=['member_team', 'view_team', 'view_organization'],
                content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
            )
        assert 'Creating custom roles that include team permissions is disabled' in str(exc)

    @override_settings(ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API=False)
    def test_system_roles_disabled(self):
        with pytest.raises(ValidationError) as exc:
            RoleDefinition.objects.create_from_permissions(name='system-inventory-viewer', permissions=['view_inventory'], content_type=None)
        assert 'System-wide roles are not enabled' in str(exc)
