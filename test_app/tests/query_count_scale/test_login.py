"""Query-count regression coverage for claims reconciliation during login."""

from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.authentication.utils.claims import ReconcileUser, RoleUserAssignmentsCache
from ansible_base.rbac.models import RoleUserAssignment


def test_claims_assignment_query_count_is_flat(_seed_large_dataset, _unblocked_db):
    """Claims reconciliation must not become an N+1 as RUAs grow."""
    counts = []

    for limit in (10, 100):
        # Keep the queryset unsliced so manage_permissions() can apply its
        # content-type filter before evaluating the limited assignment set.
        assignment_ids = list(RoleUserAssignment.objects.order_by('pk').values_list('pk', flat=True)[:limit])
        assignment_queryset = RoleUserAssignment.objects.filter(pk__in=assignment_ids)

        reconcile_user = ReconcileUser.__new__(ReconcileUser)
        reconcile_user.claims = {'rbac_roles': {}}
        reconcile_user.user = mock.Mock(role_assignments=assignment_queryset)
        reconcile_user.permissions_cache = RoleUserAssignmentsCache()
        reconcile_user._compute_organization_permissions = mock.Mock(return_value=[])
        reconcile_user._get_org_teams = mock.Mock(return_value={})
        reconcile_user.apply_permissions = mock.Mock()

        with CaptureQueriesContext(connection) as context:
            reconcile_user.manage_permissions()

        counts.append(len(context.captured_queries))

    assert counts[1] - counts[0] <= 2, f'Claims reconciliation queries grew with RUA count: {counts}'
