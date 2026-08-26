"""Benchmark for the new hard-cutoff query-count pattern (AAP-88874).

This is a proof that the new pattern -- a single hard "this endpoint must not
exceed N queries" cutoff, instead of comparing query counts at two different
result-set sizes -- actually catches the same N+1 bug that the old
delta-comparison pattern caught in `test_resources_list_extra_fields_query_count`
(see PR #1103, test_app/tests/resource_registry/test_resources_api.py).

Relies on the shared, session-scoped seeded dataset from AAP-88875 (see
`_seed_large_dataset` in this directory's `conftest.py`) instead of seeding its own
data inline -- there are already hundreds of orgs/teams/users/inventories/credentials
(and therefore resources) available by the time this test runs. The generalized,
parameterized version of this coverage across other endpoints is tracked separately
under AAP-88876.

Validation performed for AAP-88874: this test FAILS against a commit without
the AAP-88287 fix, and PASSES once PR #1109 (prefetch content_object in
ResourceViewSet) is applied.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.lib.utils.response import get_relative_url

# Surveyed against the AAP-88875 shared dataset (~700+ resources) on unfixed code: ~50+
# queries (one extra query per resource due to the un-batched content_object
# GenericForeignKey lookup). On fixed code (PR #1109's prefetch_related("content_object")),
# the same request costs ~11-15 queries regardless of result-set size. This cutoff is set
# comfortably above the fixed cost and comfortably below what the N+1 bug produces at this
# dataset's scale.
MAX_QUERIES_RESOURCE_LIST_WITH_EXTRA_FIELDS = 15


@pytest.mark.django_db
def test_resource_list_extra_fields_query_count_hard_cutoff(admin_api_client):
    """A request to resource-list?extra_fields=resource_data should never exceed
    a fixed query-count cutoff, regardless of how many resources are returned."""
    url = get_relative_url('resource-list')

    admin_api_client.get(url, {'extra_fields': 'resource_data'})  # warm up (e.g. ContentType cache)
    with CaptureQueriesContext(connection) as ctx:
        response = admin_api_client.get(url, {'extra_fields': 'resource_data'})

    assert response.status_code == 200
    # Sanity check per AAP-88874: a query-count cutoff on an empty list is meaningless.
    assert response.data['count'] > 0, "Expected seeded resources in the response; got an empty list."

    query_count = len(ctx.captured_queries)
    assert query_count <= MAX_QUERIES_RESOURCE_LIST_WITH_EXTRA_FIELDS, (
        f"resource-list?extra_fields=resource_data used {query_count} queries for "
        f"{response.data['count']} resources, exceeding the hard cutoff of "
        f"{MAX_QUERIES_RESOURCE_LIST_WITH_EXTRA_FIELDS}. ResourceDataField.to_representation() "
        f"may be doing a per-resource content_object query; ResourceViewSet.queryset needs "
        f"prefetch_related('content_object') when extra_fields=resource_data is requested."
    )
