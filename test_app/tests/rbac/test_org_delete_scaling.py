"""
Tests for organization deletion optimizations (AAP-82668).

Verifies that:
1. defer_rbac_computations batches per-team compute calls into one flush
2. no_reverse_sync suppresses cascade sync HTTP calls
3. Full cleanup with all 4 context managers leaves no orphaned artifacts
"""

from unittest import mock

import pytest
from django.test.utils import override_settings

from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation
from test_app.models import Inventory, Organization, Team
from test_app.tests.resource_registry.conftest import enable_reverse_sync  # noqa: F401

_org_counter = 0


def _create_org_with_teams(n_teams, users_per_team=0):
    """Create an organization with n_teams teams and optional users."""
    global _org_counter
    _org_counter += 1
    prefix = f'o{_org_counter}'

    from django.contrib.auth import get_user_model

    User = get_user_model()

    org = Organization.objects.create(name=f'scale-org-{prefix}-{n_teams}t')
    teams = []
    for i in range(n_teams):
        teams.append(Team.objects.create(name=f'{prefix}-team-{i}', organization=org))

    users = []
    if users_per_team > 0:
        member_rd = RoleDefinition.objects.managed.team_member
        for i, team in enumerate(teams):
            for j in range(users_per_team):
                user = User.objects.create(username=f'{prefix}-user-t{i}-u{j}')
                users.append(user)
                member_rd.give_permission(user, team)

    return org, teams, users


@pytest.mark.django_db
class TestDeferRBACCacheOnDelete:

    def test_defer_rbac_computations_batches_compute_calls(self):
        """compute_team_member_roles and recompute_role_evaluations
        each fire once (at flush) instead of once per team."""
        from ansible_base.rbac import caching
        from ansible_base.rbac.triggers import defer_rbac_computations

        org, _, _ = _create_org_with_teams(3, users_per_team=1)

        with (
            mock.patch(
                'ansible_base.rbac.triggers.compute_team_member_roles',
                wraps=caching.compute_team_member_roles,
            ) as mock_ctmr,
            mock.patch(
                'ansible_base.rbac.triggers.recompute_role_evaluations',
                wraps=caching.recompute_role_evaluations,
            ) as mock_corp,
        ):
            with defer_rbac_computations():
                org.delete()

        assert mock_ctmr.call_count <= 1
        assert mock_corp.call_count <= 1


@pytest.mark.django_db
class TestNoReverseSyncOnCascade:

    def test_no_reverse_sync_eliminates_all_http_calls(self, enable_reverse_sync):  # noqa: F811
        """Wrapping in no_reverse_sync suppresses all sync HTTP calls."""
        from ansible_base.resource_registry.signals.handlers import no_reverse_sync

        org, teams, users = _create_org_with_teams(3, users_per_team=1)

        with enable_reverse_sync():
            with override_settings(
                RESOURCE_SERVER={'URL': 'http://example.invalid', 'SECRET_KEY': 'test-key'},
            ):
                with mock.patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                    mock_response = mock.Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {}
                    mock_request.return_value = mock_response

                    with no_reverse_sync():
                        org.delete()

                    assert mock_request.call_count == 0


@pytest.mark.django_db
class TestOptimizedDeleteCleanup:
    """Verify that org deletion with all context managers leaves no
    orphaned RBAC artifacts.

    Covers integer-PK models (Organization, Team, Inventory) and UUID-PK
    models (UUIDModel) to exercise both RoleEvaluation and
    RoleEvaluationUUID cleanup paths. Also verifies provides_teams M2M
    through-table cleanup.
    """

    def test_full_cleanup_after_optimized_delete(self):
        from django.contrib.auth import get_user_model

        from ansible_base.activitystream import deferred_activity_stream
        from ansible_base.lib.utils.models import cached_system_user
        from ansible_base.rbac import permission_registry
        from ansible_base.rbac.models import RoleEvaluationUUID, RoleTeamAssignment, RoleUserAssignment
        from ansible_base.rbac.triggers import defer_rbac_computations
        from ansible_base.resource_registry.models import Resource
        from ansible_base.resource_registry.signals.handlers import defer_resource_cleanup
        from test_app.models import UUIDModel

        User = get_user_model()
        ct = permission_registry.content_type_model.objects.get_for_model

        # -- build the org graph --
        org = Organization.objects.create(name='cleanup-test-org')
        team_a = Team.objects.create(name='cleanup-team-a', organization=org)
        team_b = Team.objects.create(name='cleanup-team-b', organization=org)
        team_c = Team.objects.create(name='cleanup-team-c', organization=org)
        inv = Inventory.objects.create(name='cleanup-inv', organization=org)
        uuid_obj = UUIDModel.objects.create(organization=org)

        # -- role definitions --
        RoleDefinition.objects.managed.clear()
        member_rd = RoleDefinition.objects.managed.team_member
        org_admin_rd = RoleDefinition.objects.managed.org_admin
        inv_rd = RoleDefinition.objects.create_from_permissions(
            permissions=['change_inventory', 'view_inventory'],
            name='cleanup-inv-admin',
            content_type=ct(Inventory),
        )
        uuid_rd = RoleDefinition.objects.create_from_permissions(
            permissions=['change_uuidmodel', 'view_uuidmodel'],
            name='cleanup-uuid-admin',
            content_type=ct(UUIDModel),
        )

        # -- users --
        user_member = User.objects.create(username='cleanup-member')
        user_admin = User.objects.create(username='cleanup-admin')

        # -- assignments --
        member_rd.give_permission(user_member, team_a)
        member_rd.give_permission(user_member, team_b)
        inv_rd.give_permission(team_b, inv)
        org_admin_rd.give_permission(user_admin, org)
        member_rd.give_permission(team_a, team_c)
        uuid_rd.give_permission(user_member, uuid_obj)

        # -- collect all pks for post-delete assertions --
        org_ct = ct(Organization)
        team_ct = ct(Team)
        inv_ct = ct(Inventory)
        uuid_ct = ct(UUIDModel)
        int_cts = [org_ct.id, team_ct.id, inv_ct.id]
        int_pks = [str(org.pk)] + [str(t.pk) for t in [team_a, team_b, team_c]] + [str(inv.pk)]

        # -- sanity checks before deletion --
        assert ObjectRole.objects.filter(content_type_id__in=int_cts, object_id__in=int_pks).exists()
        assert RoleEvaluation.objects.filter(content_type_id__in=int_cts, object_id__in=int_pks).exists()
        assert RoleEvaluationUUID.objects.filter(content_type_id=uuid_ct.id, object_id=uuid_obj.pk).exists()

        provides_teams_through = ObjectRole.provides_teams.through
        assert provides_teams_through.objects.filter(team_id__in=[team_a.pk, team_b.pk, team_c.pk]).exists()

        # -- delete with all context managers --
        with cached_system_user(), deferred_activity_stream(), defer_resource_cleanup(), defer_rbac_computations():
            org.delete()

        # -- verify cleanup --
        assert not ObjectRole.objects.filter(
            content_type_id__in=int_cts + [uuid_ct.id],
            object_id__in=int_pks + [str(uuid_obj.pk)],
        ).exists(), "Orphaned ObjectRoles"

        assert not RoleEvaluation.objects.filter(content_type_id__in=int_cts, object_id__in=int_pks).exists(), "Orphaned RoleEvaluations"

        assert not RoleEvaluationUUID.objects.filter(content_type_id=uuid_ct.id, object_id=uuid_obj.pk).exists(), "Orphaned RoleEvaluationUUID"

        assert not RoleUserAssignment.objects.filter(
            content_type_id__in=int_cts + [uuid_ct.id],
            object_id__in=int_pks + [str(uuid_obj.pk)],
        ).exists(), "Orphaned RoleUserAssignments"

        assert not RoleTeamAssignment.objects.filter(content_type_id__in=int_cts, object_id__in=int_pks).exists(), "Orphaned RoleTeamAssignments"

        assert not provides_teams_through.objects.filter(team_id__in=[team_a.pk, team_b.pk, team_c.pk]).exists(), "Orphaned provides_teams"

        assert not Resource.objects.filter(
            content_type_id__in=int_cts + [uuid_ct.id],
            object_id__in=int_pks + [str(uuid_obj.pk)],
        ).exists(), "Orphaned Resources"
