from unittest import mock

import pytest

from ansible_base.rbac.caching import bulk_ancestor_roles, recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization, Team, User, UUIDModel


def _rows():
    return set(RoleEvaluation.objects.values_list('role_id', 'codename', 'content_type_id', 'object_id')) | set(
        RoleEvaluationUUID.objects.values_list('role_id', 'codename', 'content_type_id', 'object_id')
    )


def _assert_matches_full_recompute():
    rows = _rows()
    recompute_all_role_evaluations()
    assert _rows() == rows


def _rd(name, model, permissions):
    return RoleDefinition.objects.create_from_permissions(
        name=name, permissions=permissions, content_type=permission_registry.content_type_model.objects.get_for_model(model)
    )


@pytest.fixture
def team_with_ancestors(organization, member_rd, org_admin_rd):
    """A team provided by its member role and by the organization admin role, already holding other roles."""
    team = Team.objects.create(name='target', organization=organization)
    member_rd.give_permission(User.objects.create(username='member'), team)
    org_admin_rd.give_permission(User.objects.create(username='org-admin'), organization)
    other_org = Organization.objects.create(name='other')
    inv_rd = _rd('inv-change', Inventory, ['change_inventory', 'view_inventory'])
    for i in range(3):
        inv_rd.give_permission(team, Inventory.objects.create(name=f'held-{i}', organization=other_org))
    return team


def _target(kind, organization):
    """Return (role definition, object) for the assignment under test."""
    new_org = Organization.objects.create(name='new')
    if kind == 'object':
        return _rd('inv-view', Inventory, ['view_inventory']), Inventory.objects.create(name='target-inv', organization=new_org)
    if kind == 'organization':
        return _rd('org-inv', Organization, ['view_organization', 'view_inventory']), new_org
    if kind == 'already-granted':
        return _rd('inv-view', Inventory, ['view_inventory']), Inventory.objects.create(name='org-inv', organization=organization)
    if kind == 'uuid':
        return _rd('uuid-view', UUIDModel, ['view_uuidmodel']), UUIDModel.objects.create(organization=new_org)
    if kind == 'team-membership':
        return RoleDefinition.objects.managed.team_member, Team.objects.create(name='granted', organization=new_org)
    raise ValueError(kind)


TARGET_KINDS = ['object', 'organization', 'already-granted', 'uuid', 'team-membership']


@pytest.mark.django_db
@pytest.mark.parametrize('kind', TARGET_KINDS)
def test_give_and_remove_match_full_recompute(team_with_ancestors, organization, kind):
    rd, obj = _target(kind, organization)
    if kind == 'team-membership':
        Inventory.objects.create(name='granted-inv', organization=obj.organization)
        _rd('granted-team-inv', Organization, ['view_inventory']).give_permission(obj, obj.organization)
    rd.give_permission(team_with_ancestors, obj)
    _assert_matches_full_recompute()
    rd.remove_permission(team_with_ancestors, obj)
    _assert_matches_full_recompute()


@pytest.mark.django_db
@pytest.mark.parametrize('kind', TARGET_KINDS)
def test_member_permissions_follow_team_assignment(team_with_ancestors, organization, kind):
    member = User.objects.get(username='member')
    rd, obj = _target(kind, organization)
    codename = f'view_{obj._meta.model_name}'
    rd.give_permission(team_with_ancestors, obj)
    assert member.has_obj_perm(obj, codename)
    rd.remove_permission(team_with_ancestors, obj)
    if kind != 'already-granted':
        assert not member.has_obj_perm(obj, codename)


@pytest.mark.django_db
def test_chained_team_gets_new_role(organization, member_rd):
    inner = Team.objects.create(name='inner', organization=organization)
    outer = Team.objects.create(name='outer', organization=organization)
    member_rd.give_permission(outer, inner)
    user = User.objects.create(username='outer-member')
    member_rd.give_permission(user, outer)
    rd, obj = _rd('inv-view', Inventory, ['view_inventory']), Inventory.objects.create(name='inv', organization=organization)
    rd.give_permission(inner, obj)
    assert user.has_obj_perm(obj, 'view_inventory')
    _assert_matches_full_recompute()
    rd.remove_permission(inner, obj)
    assert not user.has_obj_perm(obj, 'view_inventory')
    _assert_matches_full_recompute()


@pytest.mark.django_db
@pytest.mark.parametrize('action', ['give', 'remove'])
def test_ancestor_roles_not_recomputed_in_full(team_with_ancestors, organization, action):
    rd, obj = _target('object', organization)
    if action == 'remove':
        rd.give_permission(team_with_ancestors, obj)
    ancestor_pks = {role.pk for role in bulk_ancestor_roles({team_with_ancestors.pk})}
    assert ancestor_pks
    with mock.patch.object(ObjectRole, 'needed_cache_updates', autospec=True, side_effect=ObjectRole.needed_cache_updates) as spy:
        if action == 'give':
            rd.give_permission(team_with_ancestors, obj)
        else:
            rd.remove_permission(team_with_ancestors, obj)
    recomputed = {c.args[0].pk for c in spy.call_args_list}
    assert not recomputed & ancestor_pks


@pytest.mark.django_db
def test_remove_keeps_permission_the_team_holds_through_a_parent(team_with_ancestors, organization):
    rd, obj = _target('object', organization)
    _rd('org-inv', Organization, ['view_organization', 'view_inventory']).give_permission(team_with_ancestors, obj.organization)
    rd.give_permission(team_with_ancestors, obj)
    rd.remove_permission(team_with_ancestors, obj)
    assert User.objects.get(username='member').has_obj_perm(obj, 'view_inventory')
    _assert_matches_full_recompute()
