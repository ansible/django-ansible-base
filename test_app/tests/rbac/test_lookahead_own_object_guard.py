"""a role only emits evaluations for its own object when that object is the look-ahead object."""

import pytest

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.prefetch import TypesPrefetch
from ansible_base.rbac.remote import GenericObject
from test_app.models import Inventory


def _inv_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Inventory).id


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


@pytest.mark.django_db
def test_role_on_another_object_proposes_nothing_for_the_look_ahead_object(rando, organization, team, inv_rd):
    """A team's role on inventory A must not produce evaluations while looking ahead to inventory B."""
    inv_a = Inventory.objects.create(name='inv-a', organization=organization)
    inv_rd.give_permission(team, inv_a)
    inv_a_role = ObjectRole.objects.get(role_definition=inv_rd, object_id=inv_a.pk)
    inv_b = Inventory.objects.create(name='inv-b', organization=organization)

    assert inv_a_role.expected_direct_permissions(TypesPrefetch.from_db(), look_ahead=GenericObject(_inv_ct_id(), inv_b.pk)) == set()
    assert inv_a_role.expected_direct_permissions(TypesPrefetch.from_db(), look_ahead=GenericObject(_inv_ct_id(), inv_a.pk))


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
