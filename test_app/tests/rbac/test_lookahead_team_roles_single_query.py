"""team-held roles are loaded with one query per ObjectRole, not one per team."""

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
def test_team_roles_loaded_with_one_query_per_role(rando, organization, org_inv_rd, member_rd, org_team_member_rd):
    """An org-level member_team role provides every team of the org; their roles are loaded in one query."""
    teams = [Team.objects.create(name=f'team-{i}', organization=organization) for i in range(5)]
    for team in teams:
        org_inv_rd.give_permission(team, organization)
        member_rd.give_permission(rando, team)
    org_team_member_rd.give_permission(rando, organization)
    org_member_role = ObjectRole.objects.get(role_definition=org_team_member_rd, object_id=organization.pk)
    assert org_member_role.provides_teams.count() == 5

    new_inv = Inventory.objects.create(name='inv-new', organization=organization)
    with CaptureQueriesContext(connection) as ctx:
        org_member_role.needed_cache_updates(object_pk=new_inv.pk, object_ct_id=_inv_ct_id(), target_parents=[(_org_ct_id(), organization.pk)])
    team_role_queries = [q['sql'] for q in ctx.captured_queries if '"dab_rbac_objectrole"' in q['sql'] and 'dab_rbac_roleteamassignment' in q['sql']]
    assert len(team_role_queries) == 1, team_role_queries

    after_create = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after_create
