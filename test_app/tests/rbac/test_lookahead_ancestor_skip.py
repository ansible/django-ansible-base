"""an ancestor role whose own object is unrelated to the look-ahead object skips its own evaluation."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization, Team


def _inv_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Inventory).id


def _org_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Organization).id


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


@pytest.mark.django_db
def test_other_org_admin_ancestor_issues_no_child_query(rando, org_inv_rd, member_rd, org_team_member_rd):
    """An org-level member role of ANOTHER org is an ancestor (its team holds a role here) but
    its own object cannot grant on the new inventory: no child query for it."""
    target_org = Organization.objects.create(name='target')
    other_org = Organization.objects.create(name='other')
    other_team = Team.objects.create(name='other-team', organization=other_org)
    org_inv_rd.give_permission(other_team, target_org)
    member_rd.give_permission(rando, other_team)
    org_team_member_rd.give_permission(rando, other_org)
    other_role = ObjectRole.objects.get(role_definition=org_team_member_rd, object_id=other_org.pk)
    Inventory.objects.create(name='other-inv', organization=other_org)

    new_inv = Inventory.objects.create(name='inv-new', organization=target_org)
    with CaptureQueriesContext(connection) as ctx:
        to_delete, to_add = other_role.needed_cache_updates(object_pk=new_inv.pk, object_ct_id=_inv_ct_id(), target_parents=[(_org_ct_id(), target_org.pk)])
    own_queries = [q['sql'] for q in ctx.captured_queries if f'"test_app_inventory"."organization_id" = {other_org.pk}' in q['sql']]
    assert own_queries == []
    assert not to_delete  # already up to date from the create
    assert not to_add
    assert RoleEvaluation.objects.filter(role=other_role, object_id=new_inv.pk, content_type_id=_inv_ct_id(), codename='change_inventory').exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_role_on_the_lookahead_object_itself_is_evaluated(rando, organization, inv_rd):
    """A role whose own object IS the look-ahead object keeps its own evaluation."""
    inv = Inventory.objects.create(name='inv', organization=organization)
    inv_rd.give_permission(rando, inv)
    role = ObjectRole.objects.get(role_definition=inv_rd, object_id=inv.pk)
    RoleEvaluation.objects.filter(role=role).delete()
    to_delete, to_add = role.needed_cache_updates(object_pk=inv.pk, object_ct_id=_inv_ct_id(), target_parents=[(_org_ct_id(), organization.pk)])
    assert not to_delete
    assert {(e.codename, e.object_id) for e in to_add} == {('change_inventory', inv.pk), ('view_inventory', inv.pk)}
