"""Hard-cutoff query-count benchmarks for list endpoints (AAP-88874/AAP-88876).

Asserts that a list endpoint never exceeds a fixed query-count cutoff,
regardless of result-set size -- the same pattern that caught the
`resource-list?extra_fields=resource_data` N+1 (AAP-88287) via
delta-comparison in the old `test_resources_list_extra_fields_query_count`
(PR #1103, test_app/tests/resource_registry/test_resources_api.py).

One function, parametrized over `QUERY_COUNT_CASES` -- a list of
`(url_name, query_params, max_queries)` triples -- covers multiple endpoints
in one place instead of one test function per endpoint. Add new
endpoints/scenarios as entries here rather than as new test functions.

Relies on the dataset seeded once by `_seed_large_dataset` and
`_seed_oauth_applications` (this directory's `conftest.py`), requested
explicitly below since neither is `autouse`.

No `@pytest.mark.django_db` marker -- this directory's `conftest.py` keeps DB
access unblocked for the whole session without pytest-django's per-test
atomic()/truncation machinery (see its docstring for why).
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.lib.utils.response import get_relative_url

# Cutoffs, measured against the AAP-88875 shared dataset (~150 orgs/380
# users/~2,000 assignments/~700 resources) plus 30 seeded OAuth2Applications:
# - resource-list, extra_fields=resource_data: ~50+ queries unfixed (one extra
#   query per resource, un-batched content_object lookup); ~11-15 once PR
#   #1109's prefetch_related fix lands.
# - resource-list, no extra_fields: unaffected by AAP-88287 either way
#   (measured: 4 queries); a plain, no-query-params baseline scenario.
# - organization-list (measured: 9 queries for 150 orgs) and
#   roleuserassignment-list (measured: 13 queries for ~1,900 assignments):
#   both already prefetch what their serializers need -- these are regression
#   guards, not bug hunts.
# - application-list: 154 queries for 30 applications (~5 extra queries/row --
#   OAuth2ApplicationSerializer._summary_field_tokens() does a per-row
#   obj.access_tokens.all() query, and OAuth2ApplicationViewSet.queryset has
#   no select_related/prefetch_related for its organization/created_by/
#   modified_by FKs). Filed as AAP-92618, not yet fixed.
# Cutoffs sit comfortably above each case's measured/expected-once-fixed cost.
QUERY_COUNT_CASES = [
    # TODO: uncomment once PR #1109 (AAP-88287 fix) merges -- currently fails on
    # `devel` because that fix isn't in yet (see comment above).
    # pytest.param('resource-list', {'extra_fields': 'resource_data'}, 15, id='resource_list_with_extra_fields'),
    pytest.param('resource-list', {}, 8, id='resource_list_without_extra_fields'),
    pytest.param('organization-list', {}, 15, id='organization_list'),
    pytest.param('roleuserassignment-list', {}, 20, id='role_user_assignment_list'),
    # TODO: uncomment once AAP-92618 is fixed -- currently fails on `devel`
    # (154 queries for 30 applications vs. this cutoff of 10).
    # pytest.param('application-list', {}, 10, id='application_list'),
]


@pytest.mark.parametrize('url_name, query_params, max_queries', QUERY_COUNT_CASES)
def test_list_query_count_hard_cutoff(admin_api_client, _seed_large_dataset, _seed_oauth_applications, url_name, query_params, max_queries):
    """A request to a list endpoint should never exceed a fixed query-count
    cutoff, regardless of how many objects are returned."""
    url = get_relative_url(url_name)

    admin_api_client.get(url, query_params)  # warm up (e.g. ContentType cache)
    with CaptureQueriesContext(connection) as ctx:
        response = admin_api_client.get(url, query_params)

    assert response.status_code == 200
    # Sanity check per AAP-88874: a query-count cutoff on an empty list is meaningless.
    assert response.data['count'] > 0, "Expected seeded objects in the response; got an empty list."

    query_count = len(ctx.captured_queries)
    assert query_count <= max_queries, (
        f"{url}?{query_params} used {query_count} queries for " f"{response.data['count']} objects, exceeding the hard cutoff of {max_queries}."
    )
