"""team-held role results are memoised across one look-ahead recompute."""

from unittest.mock import patch

import pytest

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from test_app.models import Inventory, Team


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


@pytest.mark.django_db
def test_lookahead_cache_is_shared_across_roles(rando, organization, org_inv_rd, member_rd):
    """The same org role reached through several teams is evaluated once per recompute."""
    teams = [Team.objects.create(name=f'team-{i}', organization=organization) for i in range(4)]
    for team in teams:
        org_inv_rd.give_permission(team, organization)
        member_rd.give_permission(rando, team)

    original = ObjectRole.expected_direct_permissions
    calls = []

    def counting(self, *args, **kwargs):
        calls.append(self.pk)
        return original(self, *args, **kwargs)

    with patch.object(ObjectRole, 'expected_direct_permissions', counting):
        Inventory.objects.create(name='inv-new', organization=organization)

    org_role = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=organization.pk)
    # the created-object path computes each relevant role's expected evaluations exactly once
    assert calls.count(org_role.pk) == 1

    after_create = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after_create
