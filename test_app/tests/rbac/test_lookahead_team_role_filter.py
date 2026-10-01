"""in look-ahead mode only team-held roles on the object or its parent chain are visited."""

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
def test_lookahead_only_loads_relevant_team_roles(rando, organization, team, org_inv_rd, inv_rd, member_rd):
    """With target_parents, team-held roles on unrelated objects are filtered out in SQL."""
    other_org = Organization.objects.create(name='other-org')
    other_inv = Inventory.objects.create(name='other-inv', organization=other_org)
    org_inv_rd.give_permission(team, organization)
    org_inv_rd.give_permission(team, other_org)  # role on another org: cannot matter for objects in `organization`
    inv_rd.give_permission(team, other_inv)
    member_rd.give_permission(rando, team)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    relevant_role = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=organization.pk)

    new_inv = Inventory.objects.create(name='inv-new', organization=organization)
    with CaptureQueriesContext(connection) as ctx:
        member_role.needed_cache_updates(object_pk=new_inv.pk, object_ct_id=_inv_ct_id(), target_parents=[(_org_ct_id(), organization.pk)])

    team_role_queries = [q['sql'] for q in ctx.captured_queries if '"dab_rbac_objectrole"' in q['sql'] and 'dab_rbac_roleteamassignment' in q['sql']]
    assert len(team_role_queries) == 1, team_role_queries
    assert f'"dab_rbac_objectrole"."object_id" = \'{organization.pk}\'' in team_role_queries[0]
    # evaluations for the new inventory come from the one relevant role only
    assert (
        RoleEvaluation.objects.filter(role=member_role, object_id=new_inv.pk, content_type_id=_inv_ct_id()).count()
        == relevant_role.permission_partials.filter(object_id=new_inv.pk, content_type_id=_inv_ct_id()).count()
    )


@pytest.mark.django_db
def test_create_matches_full_recompute_with_cross_org_teams(rando, org_inv_rd, inv_rd, member_rd, org_team_member_rd):
    """The narrowed create-path recompute must produce exactly what a full recompute produces,
    including when teams from another organization hold roles on the target organization
    and an org-level member_team role provides membership to those teams."""
    target_org = Organization.objects.create(name='target')
    other_org = Organization.objects.create(name='other')
    other_teams = [Team.objects.create(name=f'other-team-{i}', organization=other_org) for i in range(3)]
    other_invs = [Inventory.objects.create(name=f'other-inv-{i}', organization=other_org) for i in range(3)]
    for team, inv in zip(other_teams, other_invs):
        org_inv_rd.give_permission(team, target_org)  # cross-org: team from `other` holds a role on `target`
        inv_rd.give_permission(team, inv)  # plus an object role on its own org's inventory
        member_rd.give_permission(rando, team)
    org_team_member_rd.give_permission(rando, other_org)  # org-level role providing membership to all `other` teams

    for i in range(5):
        Inventory.objects.create(name=f'target-inv-{i}', organization=target_org)
    Inventory.objects.create(name='other-inv-new', organization=other_org)

    after_create = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after_create

    # sanity: the org-level member role of `other` inherited access to inventories of `target`
    org_member_role = ObjectRole.objects.get(role_definition=org_team_member_rd, object_id=other_org.pk)
    assert RoleEvaluation.objects.filter(role=org_member_role, content_type_id=_inv_ct_id(), codename='change_inventory').count() == 5 + 3
