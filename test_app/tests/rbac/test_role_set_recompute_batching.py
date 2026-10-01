"""full recomputes of a role set (e.g. after a parent change) use the chunked prefetch."""

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
def test_non_lookahead_recompute_still_correct_after_parent_change(rando, org_inv_rd, member_rd):
    """The chunked prefetch path used for full recomputes of a role set (e.g. parent change)."""
    org_a = Organization.objects.create(name='a')
    org_b = Organization.objects.create(name='b')
    team = Team.objects.create(name='t', organization=org_a)
    org_inv_rd.give_permission(team, org_a)
    org_inv_rd.give_permission(rando, org_b)
    member_rd.give_permission(rando, team)
    inv = Inventory.objects.create(name='inv', organization=org_a)
    role_a = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=org_a.pk)
    role_b = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=org_b.pk)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    assert RoleEvaluation.objects.filter(role=member_role, object_id=inv.pk, content_type_id=_inv_ct_id()).exists()

    inv.organization = org_b
    inv.save()

    assert not RoleEvaluation.objects.filter(role=role_a, object_id=inv.pk, content_type_id=_inv_ct_id()).exists()
    assert not RoleEvaluation.objects.filter(role=member_role, object_id=inv.pk, content_type_id=_inv_ct_id()).exists()
    assert RoleEvaluation.objects.filter(role=role_b, object_id=inv.pk, content_type_id=_inv_ct_id(), codename='change_inventory').exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_parent_change_query_count_does_not_grow_with_roles(rando, org_inv_rd, member_rd):
    """Query count for a parent-change recompute is bounded by chunk batching, not by role count."""
    counts = {}
    for n_teams in (2, 8):
        org_a = Organization.objects.create(name=f'a-{n_teams}')
        org_b = Organization.objects.create(name=f'b-{n_teams}')
        for i in range(n_teams):
            team = Team.objects.create(name=f't-{n_teams}-{i}', organization=org_a)
            org_inv_rd.give_permission(team, org_a)
            member_rd.give_permission(rando, team)
        inv = Inventory.objects.create(name=f'inv-{n_teams}', organization=org_a)
        inv.organization = org_b
        with CaptureQueriesContext(connection) as ctx:
            inv.save()
        counts[n_teams] = len(ctx.captured_queries)
    # the 8-team org has 4x the affected roles; batched loading must not scale the query count 4x
    assert counts[8] < 2 * counts[2], counts
