"""moving an object to another parent recomputes only that object, on the old and new parent roles."""

import re

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


def _setup(rando, org_inv_rd, member_rd, n_teams, n_other_inventories):
    org_a = Organization.objects.create(name=f'a-{n_teams}')
    org_b = Organization.objects.create(name=f'b-{n_teams}')
    for i in range(n_teams):
        team = Team.objects.create(name=f't-{n_teams}-{i}', organization=org_a)
        org_inv_rd.give_permission(team, org_a)
        member_rd.give_permission(rando, team)
    org_inv_rd.give_permission(rando, org_b)
    for i in range(n_other_inventories):
        Inventory.objects.create(name=f'other-{n_teams}-{i}', organization=org_a)
    inv = Inventory.objects.create(name=f'inv-{n_teams}', organization=org_a)
    return org_a, org_b, inv


@pytest.mark.django_db
def test_parent_change_rows_match_full_recompute(rando, org_inv_rd, member_rd):
    org_a, org_b, inv = _setup(rando, org_inv_rd, member_rd, 3, 4)
    role_a = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=org_a.pk)
    role_b = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=org_b.pk)
    inv.organization = org_b
    inv.save()
    assert not RoleEvaluation.objects.filter(role=role_a, object_id=inv.pk, content_type_id=_inv_ct_id()).exists()
    assert RoleEvaluation.objects.filter(role=role_b, object_id=inv.pk, content_type_id=_inv_ct_id(), codename='change_inventory').exists()
    for member_role in ObjectRole.objects.filter(role_definition=member_rd):
        assert not RoleEvaluation.objects.filter(role=member_role, object_id=inv.pk, content_type_id=_inv_ct_id()).exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_parent_change_of_object_with_children_still_moves_children(rando, organization, team, member_rd):
    """A namespace has collections under it; moving the namespace must move their rows too (full path)."""
    from ansible_base.rbac.models import RoleDefinition
    from test_app.models import CollectionImport, Namespace

    other_org = Organization.objects.create(name='other')
    rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_namespace', 'view_collectionimport', 'change_collectionimport'],
        name='org-ci',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    rd.give_permission(team, organization)
    rd.give_permission(rando, other_org)
    member_rd.give_permission(rando, team)
    ns = Namespace.objects.create(name='ns', organization=organization)
    ci = CollectionImport.objects.create(name='ci', namespace=ns)
    ns.organization = other_org
    ns.save()
    ci_ct = permission_registry.content_type_model.objects.get_for_model(CollectionImport).id
    other_role = ObjectRole.objects.get(role_definition=rd, object_id=other_org.pk)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    assert RoleEvaluation.objects.filter(role=other_role, content_type_id=ci_ct, object_id=ci.pk).exists()
    assert not RoleEvaluation.objects.filter(role=member_role, content_type_id=ci_ct, object_id=ci.pk).exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_parent_change_loads_only_the_moved_objects_evaluations(rando, org_inv_rd, member_rd):
    """The recompute after a parent change is a look-ahead on the moved object: existing
    evaluations are loaded for that object only, never every evaluation of the old or new org roles."""
    org_a, org_b, inv = _setup(rando, org_inv_rd, member_rd, 2, 30)
    inv.organization = org_b
    with CaptureQueriesContext(connection) as ctx:
        inv.save()
    eval_loads = [q['sql'] for q in ctx.captured_queries if '"dab_rbac_roleevaluation"' in q['sql'] and q['sql'].startswith('SELECT')]
    assert eval_loads
    # the evaluation table may appear under its own name or a subquery alias (U0)
    scoped_to_inv = re.compile(rf'("dab_rbac_roleevaluation"|U\d+)\."object_id" = {inv.pk}\b')
    for sql in eval_loads:
        assert scoped_to_inv.search(sql), sql
