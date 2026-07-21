"""
Characterization tests for organization deletion scaling (AAP-82668).

Two independent cost dimensions when deleting an organization:

1. RBAC signal cascade: rbac_post_delete_remove_object_roles fires for every
   cascade-deleted child (teams especially), running compute_team_member_roles,
   compute_object_role_permissions, and the orphan ObjectRole cleanup per team.

2. Resource registry sync: sync_to_resource_server_pre_delete fires an HTTP
   request for every cascade-deleted resource_registry model (org + each team).

These tests create scaled data and measure query counts / call counts to
establish baselines that any optimization must improve.
"""

from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext, override_settings

from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation
from test_app.models import Inventory, Organization, Team
from test_app.tests.resource_registry.conftest import enable_reverse_sync  # noqa: F401

_org_counter = 0


def _create_org_with_teams(n_teams, users_per_team=0, inventories=0):
    """Create an organization with n_teams teams, optional users and inventories.

    Returns (org, teams, users) where users is a flat list of all created users.
    """
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

    for i in range(inventories):
        Inventory.objects.create(name=f'{prefix}-inv-{i}', organization=org)

    return org, teams, users


def _count_orphan_queries(captured):
    """Count orphan ObjectRole cleanup queries (LEFT OUTER JOIN on assignment tables)."""
    return sum(
        1
        for q in captured
        if 'LEFT OUTER JOIN' in q['sql']
        and 'dab_rbac_objectrole' in q['sql']
        and ('roleuserassignment' in q['sql'].lower() or 'roleteamassignment' in q['sql'].lower())
    )


def _delete_org_with_counts(org, n_teams):
    """Delete org and return a dict of cost metrics."""
    from ansible_base.rbac import caching

    with (
        mock.patch(
            'ansible_base.rbac.triggers.compute_team_member_roles',
            wraps=caching.compute_team_member_roles,
        ) as mock_ctmr,
        mock.patch(
            'ansible_base.rbac.triggers.compute_object_role_permissions',
            wraps=caching.compute_object_role_permissions,
        ) as mock_corp,
    ):
        with CaptureQueriesContext(connection) as ctx:
            org.delete()

    total = len(ctx)
    orphan = _count_orphan_queries(ctx)
    selects = sum(1 for q in ctx if q['sql'].strip().startswith('SELECT'))
    deletes = sum(1 for q in ctx if q['sql'].strip().startswith('DELETE'))

    result = {
        'total_queries': total,
        'per_team': total / max(n_teams, 1),
        'ctmr_calls': mock_ctmr.call_count,
        'corp_calls': mock_corp.call_count,
        'orphan_queries': orphan,
        'selects': selects,
        'deletes': deletes,
    }
    print(
        f"\n  {n_teams} teams: {total} queries ({result['per_team']:.1f}/team), " f"ctmr={result['ctmr_calls']}, corp={result['corp_calls']}, orphan={orphan}"
    )
    return result


# ---------------------------------------------------------------------------
# Section 1: RBAC signal cost on organization deletion (status quo)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrgDeleteRBACScaling:
    """Characterize the query cost of RBAC signal handling during org deletion."""

    @pytest.mark.parametrize("n_teams", [1, 5, 10])
    def test_query_count_scales_with_teams_no_assignments(self, n_teams):
        """Even without role assignments, query count grows linearly with teams."""
        org, teams, _ = _create_org_with_teams(n_teams)

        with CaptureQueriesContext(connection) as ctx:
            org.delete()

        per_team = len(ctx) / max(n_teams, 1)
        print(f"\n{n_teams} teams, no assignments: {len(ctx)} queries ({per_team:.1f}/team)")
        if n_teams > 1:
            assert per_team > 5

    def test_orphan_cleanup_fixed_no_duplicate(self):
        """After fixing the duplicate on triggers.py line 347, the orphan cleanup
        should run exactly once per team (not twice).
        """
        org, teams, users = _create_org_with_teams(3, users_per_team=2)

        with CaptureQueriesContext(connection) as ctx:
            org.delete()

        orphan_count = _count_orphan_queries(ctx)
        assert orphan_count == 3, f"Expected 3 orphan cleanup queries (1 per team, duplicate fixed), got {orphan_count}"

    def test_compute_team_member_roles_runs_per_team(self):
        """compute_team_member_roles fires for every deleted team."""
        from ansible_base.rbac import caching

        org, teams, _ = _create_org_with_teams(5)

        with mock.patch(
            'ansible_base.rbac.triggers.compute_team_member_roles',
            wraps=caching.compute_team_member_roles,
        ) as mock_ctmr:
            org.delete()
            assert mock_ctmr.call_count == 5

    def test_compute_object_role_permissions_runs_per_team(self):
        """compute_object_role_permissions fires for every deleted team."""
        from ansible_base.rbac import caching

        org, teams, _ = _create_org_with_teams(5)

        with mock.patch(
            'ansible_base.rbac.triggers.compute_object_role_permissions',
            wraps=caching.compute_object_role_permissions,
        ) as mock_corp:
            org.delete()
            assert mock_corp.call_count >= 5

    def test_role_evaluation_cleanup_on_delete(self):
        """RoleEvaluation and ObjectRole rows are fully cleaned up."""
        org, teams, users = _create_org_with_teams(5, users_per_team=3)

        assert RoleEvaluation.objects.count() > 0
        assert ObjectRole.objects.count() > 0

        org.delete()

        assert RoleEvaluation.objects.count() == 0
        assert ObjectRole.objects.count() == 0

    @pytest.mark.parametrize("n_teams", [1, 5, 10, 20])
    def test_query_count_growth_rate(self, n_teams):
        """Track total query count at different team scales.

        Baselines after duplicate orphan fix (2 users/team):
          1 team:  ~56 queries (56/team)
          5 teams: ~200 queries (40/team)
         10 teams: ~380 queries (38/team)
         20 teams: ~740 queries (37/team)
        """
        org, teams, users = _create_org_with_teams(n_teams, users_per_team=2)
        result = _delete_org_with_counts(org, n_teams)
        assert result['total_queries'] > n_teams * 10


# ---------------------------------------------------------------------------
# Section 2: Resource registry sync signal scaling on organization deletion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrgDeleteSyncScaling:
    """Characterize the HTTP request cost of resource_registry signals during org deletion."""

    def test_sync_fires_per_cascaded_team(self, enable_reverse_sync):  # noqa: F811
        """Each cascade-deleted team fires its own HTTP DELETE to the resource server.
        For an org with 5 teams: 6 HTTP DELETE calls (5 teams + 1 org).
        """
        n_teams = 5
        org, teams, _ = _create_org_with_teams(n_teams)

        with enable_reverse_sync():
            with override_settings(
                RESOURCE_SERVER={'URL': 'http://example.invalid', 'SECRET_KEY': 'test-key'},
            ):
                with mock.patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                    mock_response = mock.Mock()
                    mock_response.status_code = 204
                    mock_response.json.return_value = {}
                    mock_request.return_value = mock_response

                    org.delete()

                    delete_calls = [c for c in mock_request.call_args_list if c[0][0] == 'delete']
                    assert len(delete_calls) == n_teams + 1

    @pytest.mark.parametrize("n_teams", [1, 5, 10])
    def test_sync_call_count_scales_linearly(self, n_teams, enable_reverse_sync):  # noqa: F811
        """Total HTTP requests: N+1 DELETE (one per cascade-deleted resource)."""
        org, teams, users = _create_org_with_teams(n_teams, users_per_team=2)

        with enable_reverse_sync():
            with override_settings(
                RESOURCE_SERVER={'URL': 'http://example.invalid', 'SECRET_KEY': 'test-key'},
            ):
                with mock.patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                    mock_response = mock.Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {}
                    mock_request.return_value = mock_response

                    org.delete()

                    delete_calls = sum(1 for c in mock_request.call_args_list if c[0][0] == 'delete')

                    print(f"\n{n_teams} teams: {mock_request.call_count} HTTP " f"({delete_calls} DELETE)")
                    assert delete_calls == n_teams + 1

    def test_cascade_delete_teams_redundant_sync(self, enable_reverse_sync):  # noqa: F811
        """The per-team sync HTTP DELETEs are redundant when the org cascade
        already deletes teams in all services. Documents the redundancy.
        """
        n_teams = 5
        org, teams, _ = _create_org_with_teams(n_teams)

        with enable_reverse_sync():
            with override_settings(
                RESOURCE_SERVER={'URL': 'http://example.invalid', 'SECRET_KEY': 'test-key'},
            ):
                with mock.patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                    mock_response = mock.Mock()
                    mock_response.status_code = 204
                    mock_response.json.return_value = {}
                    mock_request.return_value = mock_response

                    org.delete()

                    delete_calls = [c for c in mock_request.call_args_list if c[0][0] == 'delete']
                    # Currently fires N+1 (redundant). Ideally 1 (just org) or 0.
                    assert len(delete_calls) == n_teams + 1, (
                        f"Expected {n_teams + 1} redundant DELETE calls, got {len(delete_calls)}. " "If fewer, the cascade sync optimization is working."
                    )


# ---------------------------------------------------------------------------
# Section 3: Combined cost characterization (status quo baselines)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrgDeleteCombinedCost:
    """End-to-end cost of deleting an org, combining RBAC and sync overhead."""

    @pytest.mark.parametrize("n_teams", [1, 5, 10, 20])
    def test_total_cost_profile(self, n_teams):
        """Full cost profile after duplicate orphan fix."""
        org, teams, users = _create_org_with_teams(n_teams, users_per_team=2)
        result = _delete_org_with_counts(org, n_teams)

        assert result['ctmr_calls'] == n_teams
        assert result['corp_calls'] >= n_teams
        assert result['orphan_queries'] == n_teams


# ---------------------------------------------------------------------------
# Section 4: defer_rbac_computations batches the delete path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeferRBACCacheOnDelete:
    """Demonstrate that wrapping org.delete() in defer_rbac_computations batches
    the per-team compute calls into a single flush at context manager exit.

    Without defer_rbac_computations: N calls to compute_team_member_roles,
    N calls to compute_object_role_permissions, N orphan cleanups.

    With defer_rbac_computations: 1 call each, at flush.
    """

    @pytest.mark.parametrize("n_teams", [5, 10, 20])
    def test_defer_rbac_computations_batches_compute_calls(self, n_teams):
        """compute_team_member_roles and compute_object_role_permissions
        each fire once (at flush) instead of once per team.
        """
        from ansible_base.rbac import caching
        from ansible_base.rbac.triggers import defer_rbac_computations

        org, _, _ = _create_org_with_teams(n_teams, users_per_team=2)

        with (
            mock.patch(
                'ansible_base.rbac.triggers.compute_team_member_roles',
                wraps=caching.compute_team_member_roles,
            ) as mock_ctmr,
            mock.patch(
                'ansible_base.rbac.triggers.compute_object_role_permissions',
                wraps=caching.compute_object_role_permissions,
            ) as mock_corp,
        ):
            with CaptureQueriesContext(connection) as ctx:
                with defer_rbac_computations():
                    org.delete()

        total = len(ctx)
        orphan = _count_orphan_queries(ctx)

        print(
            f"\n  With defer_rbac_computations: {n_teams} teams: {total} queries "
            f"({total / max(n_teams, 1):.1f}/team), "
            f"ctmr={mock_ctmr.call_count}, corp={mock_corp.call_count}, orphan={orphan}"
        )

        assert mock_ctmr.call_count <= 1, f"defer_rbac_computations should batch all team recomputes into at most 1 flush call, got {mock_ctmr.call_count}"
        assert mock_corp.call_count <= 1, (
            f"defer_rbac_computations should batch object role recomputes into at most 1 flush call, " f"got {mock_corp.call_count}"
        )
        assert orphan <= 1, f"Orphan cleanup should run once at flush, got {orphan}"

        # Confirm these are strictly less than the undeferred baseline (N per team)
        assert mock_ctmr.call_count < n_teams
        assert mock_corp.call_count < n_teams

    @pytest.mark.parametrize("n_teams", [5, 10, 20])
    def test_defer_rbac_computations_reduces_query_count(self, n_teams):
        """Query count with defer_rbac_computations should be substantially lower
        than the undeferred baseline (~38 queries/team).
        """
        from ansible_base.rbac.triggers import defer_rbac_computations

        # Baseline: without defer
        org_baseline, _, _ = _create_org_with_teams(n_teams, users_per_team=2)
        with CaptureQueriesContext(connection) as ctx_baseline:
            org_baseline.delete()
        baseline = len(ctx_baseline)

        # Deferred: with defer
        org_deferred, _, _ = _create_org_with_teams(n_teams, users_per_team=2)
        with CaptureQueriesContext(connection) as ctx_deferred:
            with defer_rbac_computations():
                org_deferred.delete()
        deferred = len(ctx_deferred)

        print(f"\n  {n_teams} teams: baseline={baseline}, deferred={deferred}, " f"reduction={baseline - deferred} ({(baseline - deferred)/baseline*100:.0f}%)")

        assert deferred < baseline, f"defer_rbac_computations should reduce query count: baseline={baseline}, deferred={deferred}"

    def test_deferred_delete_still_cleans_up_fully(self):
        """RoleEvaluation and ObjectRole rows are fully cleaned up even with deferral."""
        from ansible_base.rbac.triggers import defer_rbac_computations

        org, teams, users = _create_org_with_teams(5, users_per_team=3)
        assert RoleEvaluation.objects.count() > 0
        assert ObjectRole.objects.count() > 0

        with defer_rbac_computations():
            org.delete()

        assert RoleEvaluation.objects.count() == 0
        assert ObjectRole.objects.count() == 0


# ---------------------------------------------------------------------------
# Section 5: no_reverse_sync suppresses cascade sync calls
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNoReverseSyncOnCascade:
    """Demonstrate that wrapping org.delete() in no_reverse_sync() from the
    resource_registry eliminates all per-team HTTP calls.

    This is the correct approach for (3): when gateway initiates the org delete,
    the service should suppress reverse sync because gateway already knows.
    """

    @pytest.mark.parametrize("n_teams", [1, 5, 10])
    def test_no_reverse_sync_eliminates_all_http_calls(self, n_teams, enable_reverse_sync):  # noqa: F811
        """Wrapping in no_reverse_sync suppresses all sync HTTP calls."""
        from ansible_base.resource_registry.signals.handlers import no_reverse_sync

        org, teams, users = _create_org_with_teams(n_teams, users_per_team=2)

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

                    assert mock_request.call_count == 0, f"Expected 0 HTTP calls with no_reverse_sync, got {mock_request.call_count}"

    def test_no_reverse_sync_rbac_queries_unchanged(self):
        """no_reverse_sync doesn't reduce query count — only HTTP calls.
        The RBAC signal cascade (compute_team_member_roles etc.) still fires.

        Compare to baselines in TestOrgDeleteCombinedCost — should match.
        """
        from ansible_base.rbac import caching
        from ansible_base.resource_registry.signals.handlers import no_reverse_sync

        n_teams = 10
        org, _, _ = _create_org_with_teams(n_teams, users_per_team=2)

        with (
            mock.patch(
                'ansible_base.rbac.triggers.compute_team_member_roles',
                wraps=caching.compute_team_member_roles,
            ) as mock_ctmr,
            mock.patch(
                'ansible_base.rbac.triggers.compute_object_role_permissions',
                wraps=caching.compute_object_role_permissions,
            ) as mock_corp,
        ):
            with CaptureQueriesContext(connection) as ctx:
                with no_reverse_sync():
                    org.delete()

        total = len(ctx)
        print(
            f"\n  With no_reverse_sync: {n_teams} teams: {total} queries "
            f"({total / max(n_teams, 1):.1f}/team), "
            f"ctmr={mock_ctmr.call_count}, corp={mock_corp.call_count}"
        )

        assert mock_ctmr.call_count == n_teams
        assert mock_corp.call_count >= n_teams

    @pytest.mark.parametrize("n_teams", [1, 5, 10])
    def test_no_reverse_sync_for_suppresses_team_sync_only(self, n_teams, enable_reverse_sync):  # noqa: F811
        """no_reverse_sync_for(Team) suppresses team DELETE sync calls
        while allowing the org DELETE sync to fire.

        This is the selective approach: the caller knows that cascade-deleted
        teams don't need individual sync calls because the gateway will
        cascade internally. But the org itself still needs its sync call.
        """
        from ansible_base.resource_registry.signals.handlers import no_reverse_sync_for

        org, teams, _ = _create_org_with_teams(n_teams, users_per_team=2)

        with enable_reverse_sync():
            with override_settings(
                RESOURCE_SERVER={'URL': 'http://example.invalid', 'SECRET_KEY': 'test-key'},
            ):
                with mock.patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                    mock_response = mock.Mock()
                    mock_response.status_code = 204
                    mock_response.json.return_value = {}
                    mock_request.return_value = mock_response

                    with no_reverse_sync_for(Team):
                        org.delete()

                    delete_calls = [c for c in mock_request.call_args_list if c[0][0] == 'delete']
                    assert len(delete_calls) == 1, f"Expected 1 DELETE call (org only), got {len(delete_calls)}. " "Team sync should be suppressed."


# ---------------------------------------------------------------------------
# Section 6: Full cleanup correctness with all context managers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOptimizedDeleteCleanup:
    """Verify that org deletion with all context managers leaves no
    orphaned RBAC artifacts.

    Covers integer-PK models (Organization, Team, Inventory) and UUID-PK
    models (UUIDModel) to exercise both RoleEvaluation and
    RoleEvaluationUUID cleanup paths. Also verifies provides_teams M2M
    through-table cleanup.

    TODO: audit team-of-teams cleanup correctness — the deferred path
    skips per-team provides_teams queries (M2M is cascade-deleted before
    flush), so nested team graphs may need a dedicated fix.
    """

    def test_full_cleanup_after_optimized_delete(self):
        from django.contrib.auth import get_user_model

        from ansible_base.activitystream import deferred_activity_stream
        from ansible_base.rbac import permission_registry
        from ansible_base.rbac.models import RoleEvaluationUUID, RoleTeamAssignment, RoleUserAssignment
        from ansible_base.rbac.triggers import defer_rbac_computations
        from ansible_base.resource_registry.models import Resource
        from ansible_base.resource_registry.signals.handlers import defer_resource_cleanup, no_reverse_sync_for
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
        # managed org_admin includes member_team — exercises provides_teams
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
        # user → team membership
        member_rd.give_permission(user_member, team_a)
        member_rd.give_permission(user_member, team_b)
        # team → inventory (team_b can edit the inventory)
        inv_rd.give_permission(team_b, inv)
        # user → org admin (includes member_team, creates provides_teams entries)
        org_admin_rd.give_permission(user_admin, org)
        # team-of-teams: team_a is member of team_c
        member_rd.give_permission(team_a, team_c)
        # user → UUID-pk resource
        uuid_rd.give_permission(user_member, uuid_obj)

        # -- collect all pks for post-delete assertions --
        org_ct = ct(Organization)
        team_ct = ct(Team)
        inv_ct = ct(Inventory)
        uuid_ct = ct(UUIDModel)
        int_cts = [org_ct.id, team_ct.id, inv_ct.id]
        int_pks = [str(org.pk)] + [str(t.pk) for t in [team_a, team_b, team_c]] + [str(inv.pk)]

        # -- sanity checks before deletion --
        assert ObjectRole.objects.filter(
            content_type_id__in=int_cts,
            object_id__in=int_pks,
        ).exists(), "Sanity: ObjectRoles should exist before delete"

        assert RoleEvaluation.objects.filter(
            content_type_id__in=int_cts,
            object_id__in=int_pks,
        ).exists(), "Sanity: RoleEvaluations should exist before delete"

        assert RoleEvaluationUUID.objects.filter(
            content_type_id=uuid_ct.id,
            object_id=uuid_obj.pk,
        ).exists(), "Sanity: RoleEvaluationUUID should exist for UUID resource"

        provides_teams_through = ObjectRole.provides_teams.through
        assert provides_teams_through.objects.filter(
            team_id__in=[team_a.pk, team_b.pk, team_c.pk],
        ).exists(), "Sanity: provides_teams entries should exist before delete"

        # -- delete with all context managers --
        with deferred_activity_stream():
            with no_reverse_sync_for(Team):
                with defer_resource_cleanup():
                    with defer_rbac_computations():
                        org.delete()

        # -- verify cleanup --
        remaining_object_roles = ObjectRole.objects.filter(
            content_type_id__in=int_cts + [uuid_ct.id],
            object_id__in=int_pks + [str(uuid_obj.pk)],
        )
        assert not remaining_object_roles.exists(), f"Orphaned ObjectRoles: {list(remaining_object_roles.values_list('id', 'content_type_id', 'object_id'))}"

        remaining_evals = RoleEvaluation.objects.filter(
            content_type_id__in=int_cts,
            object_id__in=int_pks,
        )
        assert not remaining_evals.exists(), f"Orphaned RoleEvaluations: {list(remaining_evals.values_list('id', 'codename', 'content_type_id', 'object_id'))}"

        remaining_uuid_evals = RoleEvaluationUUID.objects.filter(
            content_type_id=uuid_ct.id,
            object_id=uuid_obj.pk,
        )
        assert (
            not remaining_uuid_evals.exists()
        ), f"Orphaned RoleEvaluationUUID: {list(remaining_uuid_evals.values_list('id', 'codename', 'content_type_id', 'object_id'))}"

        remaining_user_assignments = RoleUserAssignment.objects.filter(
            content_type_id__in=int_cts + [uuid_ct.id],
            object_id__in=int_pks + [str(uuid_obj.pk)],
        )
        assert (
            not remaining_user_assignments.exists()
        ), f"Orphaned RoleUserAssignments: {list(remaining_user_assignments.values_list('id', 'user_id', 'object_role_id'))}"

        remaining_team_assignments = RoleTeamAssignment.objects.filter(
            content_type_id__in=int_cts,
            object_id__in=int_pks,
        )
        assert (
            not remaining_team_assignments.exists()
        ), f"Orphaned RoleTeamAssignments: {list(remaining_team_assignments.values_list('id', 'team_id', 'object_role_id'))}"

        remaining_provides = provides_teams_through.objects.filter(
            team_id__in=[team_a.pk, team_b.pk, team_c.pk],
        )
        assert not remaining_provides.exists(), f"Orphaned provides_teams: {list(remaining_provides.values_list('objectrole_id', 'team_id'))}"

        remaining_resources = Resource.objects.filter(
            content_type_id__in=int_cts + [uuid_ct.id],
            object_id__in=int_pks + [str(uuid_obj.pk)],
        )
        assert not remaining_resources.exists(), f"Orphaned Resources: {list(remaining_resources.values_list('id', 'content_type_id', 'object_id'))}"
