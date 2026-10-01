"""a role only emits evaluations for its own object when that object is the look-ahead object."""

import pytest

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization


def _inv_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Inventory).id


def _org_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Organization).id


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


@pytest.mark.django_db
def test_team_object_roles_on_other_objects_are_not_proposed(rando, organization, team, org_inv_rd, inv_rd, member_rd):
    """A team's role on inventory A must not produce evaluations while looking ahead to inventory B."""
    inv_a = Inventory.objects.create(name='inv-a', organization=organization)
    org_inv_rd.give_permission(team, organization)
    inv_rd.give_permission(team, inv_a)
    member_rd.give_permission(rando, team)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)

    inv_b = Inventory.objects.create(name='inv-b', organization=organization)
    # simulate the state during the post_save signal: nothing cached yet for inv_b
    RoleEvaluation.objects.filter(role=member_role, object_id=inv_b.pk, content_type_id=_inv_ct_id()).delete()

    to_delete, to_add = member_role.needed_cache_updates(object_pk=inv_b.pk, object_ct_id=_inv_ct_id())
    assert not to_delete
    assert to_add
    assert {(e.content_type_id, e.object_id) for e in to_add} == {(_inv_ct_id(), inv_b.pk)}


@pytest.mark.django_db
def test_create_matches_full_recompute_with_object_roles(rando, organization, team, org_inv_rd, inv_rd, member_rd):
    inv_a = Inventory.objects.create(name='inv-a', organization=organization)
    org_inv_rd.give_permission(team, organization)
    inv_rd.give_permission(team, inv_a)
    member_rd.give_permission(rando, team)
    Inventory.objects.create(name='inv-b', organization=organization)
    after_create = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after_create
