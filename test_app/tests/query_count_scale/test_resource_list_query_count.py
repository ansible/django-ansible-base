"""Hard-cutoff query-count benchmark for resource-list (AAP-88874).

Asserts resource-list never exceeds a fixed query-count cutoff, regardless of
result-set size -- catches the same N+1 bug that
`test_resources_list_extra_fields_query_count` caught via delta-comparison
(PR #1103, test_app/tests/resource_registry/test_resources_api.py).

One function, parametrized over `QUERY_COUNT_CASES`, covers both
`extra_fields=resource_data` (triggers AAP-88287's N+1) and a plain
no-`extra_fields` baseline. Add new endpoints/scenarios as entries in
`QUERY_COUNT_CASES` rather than new test functions (see AAP-88876).

Relies on the dataset seeded once by `_seed_large_dataset` (this directory's
`conftest.py`), requested explicitly below since it's not `autouse`.

No `@pytest.mark.django_db` marker -- this directory's `conftest.py` keeps DB
access unblocked for the whole session without pytest-django's per-test
atomic()/truncation machinery (see its docstring for why).
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.lib.utils.response import get_relative_url

# Cutoffs, measured against the AAP-88875 shared dataset (~700 resources):
# - extra_fields=resource_data: ~50+ queries unfixed (one extra query per
#   resource, un-batched content_object lookup); ~11-15 once PR #1109's
#   prefetch_related fix lands.
# - No extra_fields: unaffected by AAP-88287 either way (measured: 4 queries);
#   included as a plain, no-query-params baseline scenario.
# Both cutoffs sit comfortably above their fixed cost and below what the N+1
# bug produces at this scale.
QUERY_COUNT_CASES = [
    # TODO: uncomment once PR #1109 (AAP-88287 fix) merges -- currently fails on
    # `devel` because that fix isn't in yet (see module docstring above).
    # pytest.param({'extra_fields': 'resource_data'}, 15, id='with_extra_fields'),
    pytest.param({}, 8, id='without_extra_fields'),
]


@pytest.mark.parametrize('query_params, max_queries', QUERY_COUNT_CASES)
def test_resource_list_query_count_hard_cutoff(admin_api_client, _seed_large_dataset, query_params, max_queries):
    """A request to resource-list should never exceed a fixed query-count cutoff,
    regardless of how many resources are returned, whether or not extra_fields is
    requested."""
    url = get_relative_url('resource-list')

    admin_api_client.get(url, query_params)  # warm up (e.g. ContentType cache)
    with CaptureQueriesContext(connection) as ctx:
        response = admin_api_client.get(url, query_params)

    assert response.status_code == 200
    # Sanity check per AAP-88874: a query-count cutoff on an empty list is meaningless.
    assert response.data['count'] > 0, "Expected seeded resources in the response; got an empty list."

    query_count = len(ctx.captured_queries)
    assert query_count <= max_queries, (
        f"{url}?{query_params} used {query_count} queries for "
        f"{response.data['count']} resources, exceeding the hard cutoff of "
        f"{max_queries}. ResourceDataField.to_representation() may be doing a "
        f"per-resource content_object query; ResourceViewSet.queryset needs "
        f"prefetch_related('content_object') when extra_fields=resource_data is requested."
    )
