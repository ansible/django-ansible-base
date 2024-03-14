import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.exceptions import ValidationError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABPermission, ObjectRole, RoleDefinition, RoleEvaluation
from ansible_base.rbac.validators import validate_permissions_for_model
from test_app.models import ExampleEvent, Organization


@pytest.mark.django_db
def test_reuse_by_permission_list():
    demo_permissions = ['view_inventory', 'delete_inventory']
    rd1, created = RoleDefinition.objects.get_or_create(permissions=demo_permissions, name='test-deleter')
    assert created

    # Will ignore name in favor of permissions
    rd2, created = RoleDefinition.objects.get_or_create(permissions=demo_permissions, name='test-deleter-two')
    assert (not created) and (rd2 == rd1)


@pytest.mark.django_db
def test_root_resource_add_invalid():
    with pytest.raises(ValidationError) as exc:
        org_admin, created = RoleDefinition.objects.get_or_create(
            name='org-view', permissions=['add_organization'], defaults={'content_type': ContentType.objects.get_for_model(Organization)}
        )
    assert 'Permissions "add_organization" are not valid for organization roles' in str(exc)


@pytest.mark.django_db
def test_missing_view_permission():
    with pytest.raises(ValidationError) as exc:
        RoleDefinition.objects.create_from_permissions(
            permissions=['change_organization'], name='only-change-org', content_type=ContentType.objects.get_for_model(Organization)
        )
    assert 'needs to include view' in str(exc)


@pytest.mark.django_db
def test_permission_for_unregistered_model():
    with pytest.raises(DABPermission.DoesNotExist):
        validate_permissions_for_model(
            permissions=[DABPermission.objects.get(codename='view_exampleevent')],
            content_type=ContentType.objects.get_for_model(ExampleEvent),
        )


@pytest.mark.django_db
def test_other_models_immutable(organization, rando, org_inv_rd):
    org_inv_rd.give_permission(rando, organization)
    object_role = ObjectRole.objects.first()
    role_evaluation = RoleEvaluation.objects.first()
    with pytest.raises(RuntimeError):
        object_role.save()
    with pytest.raises(RuntimeError):
        role_evaluation.save()


@pytest.mark.django_db
def test_change_role_definition_permission(organization, team, inventory, member_rd, org_inv_rd):
    team_user = permission_registry.user_model.objects.create(username='team-user')
    org_user = permission_registry.user_model.objects.create(username='org-user')

    org_inv_rd.give_permission(team, organization)
    org_inv_rd.give_permission(org_user, organization)
    member_rd.give_permission(team_user, team)

    # sanity
    assert [u.has_obj_perm(inventory, 'update') for u in (team_user, org_user)] == [False, False]

    new_perm = permission_registry.permission_qs.get(codename='update_inventory')
    org_inv_rd.permissions.add(new_perm)

    # Users get new permission
    assert [u.has_obj_perm(inventory, 'update') for u in (team_user, org_user)] == [True, True]

    # Removing takes away the permission
    org_inv_rd.permissions.remove(new_perm)
    assert [u.has_obj_perm(inventory, 'update') for u in (team_user, org_user)] == [False, False]


@pytest.mark.django_db
def test_change_role_definition_member_permission(organization, inventory, org_member_rd, member_rd, inv_rd):
    team_user = permission_registry.user_model.objects.create(username='team-user')
    org_team_user = permission_registry.user_model.objects.create(username='org-team-user')
    team = permission_registry.team_model.objects.create(name='ateam', organization=organization)
    org_team = permission_registry.team_model.objects.create(name='org-team', organization=organization)
    in_org_team = permission_registry.team_model.objects.create(name='child-team', organization=organization)

    inv_rd.give_permission(team, inventory)
    member_rd.give_permission(team_user, team)

    org_member_rd.give_permission(org_team, organization)
    member_rd.give_permission(org_team_user, org_team)
    inv_rd.give_permission(in_org_team, inventory)

    # sanity
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [True, True]

    # Removing memberships takes away the permission
    member_perm = permission_registry.permission_qs.get(codename='member_team')
    member_rd.permissions.remove(member_perm)
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [False, False]

    # Adding it back restores them
    member_rd.permissions.add(member_perm)
    assert [u.has_obj_perm(inventory, 'change') for u in (team_user, org_team_user)] == [True, True]
