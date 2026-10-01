"""object-centric recompute used when a child object is created."""

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


from ansible_base.rbac.caching import recompute_role_evaluations_for_created  # noqa: E402
from ansible_base.rbac.triggers import object_roles_for_parents  # noqa: E402


def _build_org(rando, org_inv_rd, inv_rd, member_rd, name, n_teams):
    org = Organization.objects.create(name=name)
    teams = [Team.objects.create(name=f'{name}-team-{i}', organization=org) for i in range(n_teams)]
    for team in teams:
        org_inv_rd.give_permission(team, org)
        member_rd.give_permission(rando, team)
        inv = Inventory.objects.create(name=f'{name}-{team.name}-inv', organization=org)
        inv_rd.give_permission(team, inv)
    return org, teams


@pytest.mark.django_db
def test_created_recompute_matches_full_recompute(rando, org_inv_rd, inv_rd, member_rd, org_team_member_rd, org_admin_rd):
    target_org, _ = _build_org(rando, org_inv_rd, inv_rd, member_rd, 'target', 4)
    other_org, other_teams = _build_org(rando, org_inv_rd, inv_rd, member_rd, 'other', 3)
    for team in other_teams:
        org_inv_rd.give_permission(team, target_org)  # cross-org
    org_team_member_rd.give_permission(rando, other_org)  # org-level member_team role, provides all `other` teams
    org_admin_rd.give_permission(rando, target_org)
    # team of teams: membership in other_teams[0] grants membership in target's first team
    member_rd.give_permission(other_teams[0], Team.objects.get(name='target-team-0'))

    Inventory.objects.create(name='target-new', organization=target_org)
    Inventory.objects.create(name='other-new', organization=other_org)

    after_create = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after_create


@pytest.mark.django_db
def test_created_recompute_query_count_does_not_grow_with_teams(rando, org_inv_rd, inv_rd, member_rd):
    counts = {}
    for n_teams in (2, 8):
        org, _ = _build_org(rando, org_inv_rd, inv_rd, member_rd, f'org-{n_teams}', n_teams)
        with CaptureQueriesContext(connection) as ctx:
            Inventory.objects.create(name=f'org-{n_teams}-new', organization=org)
        counts[n_teams] = len(ctx.captured_queries)
    assert counts[8] == counts[2], counts


@pytest.mark.django_db
def test_created_recompute_removes_stale_rows_and_adds_missing(rando, organization, team, org_inv_rd, member_rd):
    org_inv_rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)
    inv = Inventory.objects.create(name='inv', organization=organization)
    org_role = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=organization.pk)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)

    # simulate a stale row that should not exist and a missing row that should
    stale = RoleEvaluation.objects.create(role=member_role, codename='bogus_inventory', content_type_id=_inv_ct_id(), object_id=inv.pk)
    RoleEvaluation.objects.filter(role=org_role, codename='change_inventory', content_type_id=_inv_ct_id(), object_id=inv.pk).delete()

    to_update = object_roles_for_parents({(permission_registry.content_type_model.objects.get_for_model(Organization), organization.pk)})
    assert {org_role, member_role} <= to_update
    recompute_role_evaluations_for_created(to_update, object_pk=inv.pk, object_ct_id=_inv_ct_id(), target_parents=[(_org_ct_id(), organization.pk)])

    assert not RoleEvaluation.objects.filter(pk=stale.pk).exists()
    assert RoleEvaluation.objects.filter(role=org_role, codename='change_inventory', content_type_id=_inv_ct_id(), object_id=inv.pk).exists()
    assert RoleEvaluation.objects.filter(role=member_role, codename='change_inventory', content_type_id=_inv_ct_id(), object_id=inv.pk).exists()


@pytest.mark.django_db
def test_created_recompute_with_no_roles_is_a_no_op(organization, django_assert_num_queries):
    from ansible_base.rbac.prefetch import TypesPrefetch

    types_prefetch = TypesPrefetch.from_db()
    with django_assert_num_queries(0):
        recompute_role_evaluations_for_created(
            [], object_pk=1, object_ct_id=_inv_ct_id(), target_parents=[(_org_ct_id(), organization.pk)], types_prefetch=types_prefetch
        )
