import pytest

from ansible_base.rbac.caching import object_roles_for_parents, recompute_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.triggers import _fast_create_evaluations, get_parent_ids
from test_app.models import Inventory, Organization, UUIDModel


def _eval_set(obj):
    """Return all RoleEvaluation entries for an object as a set of (codename, ct_id, role_id) tuples."""
    ct = permission_registry.content_type_model.objects.get_for_model(obj)
    model = RoleEvaluationUUID if isinstance(obj.pk, __import__('uuid').UUID) else RoleEvaluation
    return set(model.objects.filter(object_id=obj.pk, content_type_id=ct.id).values_list('codename', 'content_type_id', 'role_id'))


def _recompute_eval_set(obj):
    """Delete all evaluations for obj, recompute via the original path, return the resulting set."""
    ct = permission_registry.content_type_model.objects.get_for_model(obj)
    model = RoleEvaluationUUID if isinstance(obj.pk, __import__('uuid').UUID) else RoleEvaluation
    model.objects.filter(object_id=obj.pk, content_type_id=ct.id).delete()
    parent_gfks = get_parent_ids(obj)
    if parent_gfks:
        to_update = object_roles_for_parents(set(parent_gfks))
        recompute_role_evaluations(to_update, object_pk=obj.pk, object_ct_id=ct.id)
    return set(model.objects.filter(object_id=obj.pk, content_type_id=ct.id).values_list('codename', 'content_type_id', 'role_id'))


@pytest.mark.django_db
def test_fast_create_matches_recompute(organization, org_inv_rd, team, member_rd, rando):
    """The fast path produces the same evaluations as the full recompute path."""
    member_rd.give_permission(rando, team)
    org_inv_rd.give_permission(team, organization)

    inv = Inventory.objects.create(name='fast-create-test', organization=organization)
    fast_evals = _eval_set(inv)
    recomputed_evals = _recompute_eval_set(inv)

    assert fast_evals == recomputed_evals
    assert len(fast_evals) > 0


@pytest.mark.django_db
def test_fast_create_no_parent(db):
    """Objects without a parent org produce no evaluations."""
    org = Organization.objects.create(name='top-level-test')
    ct = permission_registry.content_type_model.objects.get_for_model(org)
    evals = RoleEvaluation.objects.filter(object_id=org.pk, content_type_id=ct.id)
    assert not evals.exists()


@pytest.mark.django_db
def test_fast_create_no_roles_on_org(organization):
    """When the org has no ObjectRoles, no evaluations are created."""
    assert not ObjectRole.objects.filter(
        object_id=str(organization.pk),
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    ).exists()

    inv = Inventory.objects.create(name='no-roles-test', organization=organization)
    assert not _eval_set(inv)


@pytest.mark.django_db
def test_fast_create_no_matching_permissions(organization, team, member_rd):
    """Org role that doesn't grant permissions on the created object's content type
    produces no evaluations for that object."""
    # org_team_member_rd grants member_team + view_team — nothing about inventories
    org_team_rd = RoleDefinition.objects.create_from_permissions(
        permissions=[permission_registry.team_permission, f'view_{permission_registry.team_model._meta.model_name}'],
        name='org-team-only',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    org_team_rd.give_permission(team, organization)

    inv = Inventory.objects.create(name='no-match-test', organization=organization)
    inv_evals = _eval_set(inv)
    assert not inv_evals


@pytest.mark.django_db
def test_fast_create_multiple_role_types_on_team(organization, team, member_rd, rando):
    """A team with multiple org-level role types gets the combined codenames."""
    member_rd.give_permission(rando, team)

    inv_admin_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'change_inventory', 'view_inventory'],
        name='org-inv-view-change',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    inv_delete_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'delete_inventory', 'view_inventory'],
        name='org-inv-view-delete',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    inv_admin_rd.give_permission(team, organization)
    inv_delete_rd.give_permission(team, organization)

    inv = Inventory.objects.create(name='multi-role-test', organization=organization)
    fast_evals = _eval_set(inv)
    recomputed_evals = _recompute_eval_set(inv)

    assert fast_evals == recomputed_evals
    codenames = {e[0] for e in fast_evals}
    assert 'change_inventory' in codenames
    assert 'delete_inventory' in codenames
    assert 'view_inventory' in codenames


@pytest.mark.django_db
def test_fast_create_uuid_pk(organization, org_inv_rd, team, member_rd, rando):
    """The fast path works with UUID primary keys using RoleEvaluationUUID."""
    member_rd.give_permission(rando, team)

    uuid_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'change_uuidmodel', 'view_uuidmodel'],
        name='org-uuid-admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    uuid_rd.give_permission(team, organization)

    obj = UUIDModel.objects.create(organization=organization)
    ct = permission_registry.content_type_model.objects.get_for_model(obj)

    fast_evals = set(
        RoleEvaluationUUID.objects.filter(object_id=obj.pk, content_type_id=ct.id).values_list('codename', 'content_type_id', 'role_id')
    )
    assert len(fast_evals) > 0

    # Verify against recompute
    recomputed_evals = _recompute_eval_set(obj)
    assert fast_evals == recomputed_evals


@pytest.mark.django_db
def test_fast_create_copy_double_save(organization, org_inv_rd, team, member_rd, rando):
    """Simulates the copy view's double save: first save creates evaluations,
    second save (updating fields) should not trigger a full recompute."""
    member_rd.give_permission(rando, team)
    org_inv_rd.give_permission(team, organization)

    inv = Inventory.objects.create(name='copy-source', organization=organization)
    first_save_evals = _eval_set(inv)
    assert len(first_save_evals) > 0

    # Second save — simulates what the copy view does after creation
    inv.name = 'copy-target'
    inv.save()

    after_second_save_evals = _eval_set(inv)
    assert first_save_evals == after_second_save_evals


@pytest.mark.django_db
def test_fast_create_direct_user_assignment(organization, org_inv_rd, rando):
    """Direct user role assignment on the org (not via team) also produces correct evaluations."""
    org_inv_rd.give_permission(rando, organization)

    inv = Inventory.objects.create(name='direct-user-test', organization=organization)
    fast_evals = _eval_set(inv)
    recomputed_evals = _recompute_eval_set(inv)

    assert fast_evals == recomputed_evals
    assert len(fast_evals) > 0


@pytest.mark.django_db
def test_fast_create_multiple_teams(organization, org_inv_rd, member_rd):
    """Multiple teams with the same org-level role all get evaluations."""
    teams = []
    for i in range(5):
        from test_app.models import User
        t = permission_registry.team_model.objects.create(name=f'team-{i}', organization=organization)
        u = User.objects.create(username=f'user-{i}')
        member_rd.give_permission(u, t)
        org_inv_rd.give_permission(t, organization)
        teams.append(t)

    inv = Inventory.objects.create(name='multi-team-test', organization=organization)
    fast_evals = _eval_set(inv)
    recomputed_evals = _recompute_eval_set(inv)

    assert fast_evals == recomputed_evals
    # Each team's Team Member ObjectRole should have evaluations
    team_ct = permission_registry.content_type_model.objects.get_for_model(permission_registry.team_model)
    team_member_role_ids = set(
        ObjectRole.objects.filter(
            content_type=team_ct,
            object_id__in=[str(t.pk) for t in teams],
            role_definition__permissions__codename=permission_registry.team_permission,
        ).values_list('id', flat=True)
    )
    eval_role_ids = {e[2] for e in fast_evals}
    assert team_member_role_ids.issubset(eval_role_ids)
