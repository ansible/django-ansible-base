"""Hard-cutoff query-count benchmarks for list endpoints (AAP-88874/AAP-88876).

Asserts each list endpoint stays under a fixed query-count cutoff regardless
of result-set size -- the pattern that caught the AAP-88287 N+1.

One function, parametrized over `QUERY_COUNT_CASES` (`url_name, query_params,
max_queries` triples). Add new endpoints/scenarios as list entries here, not
new test functions.

Uses the shared dataset from this directory's `conftest.py`. No
`@pytest.mark.django_db` marker needed -- see that module's docstring.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.lib.utils.response import get_relative_url

# Measured against the AAP-88875 shared dataset (~150 orgs/380 users/~2,000
# assignments) plus 30 each of seeded OAuth2Applications/AccessTokens/
# AuthenticatorMaps. Page size is 50, so counts are per-page, not per-total-rows.
#
# Passing (regression guards, already well-optimized): resource-list,
# organization-list, roleuserassignment-list, team-list, user-list,
# inventory-list, roledefinition-list, roleteamassignment-list,
# authenticator-list, resourcetype-list, dabcontenttype-list,
# dabpermission-list, activitystream-list, aap_flags_states-list.
#
# Failing (real N+1s found this way -- disabled below until fixed, see TODOs).
QUERY_COUNT_CASES = [
    # TODO: uncomment once #1109 (AAP-88287 fix) merges (~50+q/2 rows vs cutoff 15).
    # pytest.param('resource-list', {'extra_fields': 'resource_data'}, 15, id='resource_list_with_extra_fields'),
    pytest.param('resource-list', {}, 8, id='resource_list_without_extra_fields'),
    pytest.param('organization-list', {}, 15, id='organization_list'),
    pytest.param('roleuserassignment-list', {}, 20, id='role_user_assignment_list'),
    pytest.param('team-list', {}, 15, id='team_list'),
    pytest.param('user-list', {}, 15, id='user_list'),
    pytest.param('inventory-list', {}, 12, id='inventory_list'),
    pytest.param('roledefinition-list', {}, 15, id='role_definition_list'),
    pytest.param('roleteamassignment-list', {}, 20, id='role_team_assignment_list'),
    pytest.param('authenticator-list', {}, 12, id='authenticator_list'),
    pytest.param('resourcetype-list', {}, 10, id='resource_type_list'),
    pytest.param('dabcontenttype-list', {}, 10, id='dab_content_type_list'),
    pytest.param('dabpermission-list', {}, 10, id='dab_permission_list'),
    pytest.param('activitystream-list', {}, 12, id='activity_stream_list'),
    pytest.param('aap_flags_states-list', {}, 12, id='aap_flags_states_list'),
    # TODO: uncomment once AAP-92618 is fixed (154q/30 rows vs cutoff 10).
    # pytest.param('application-list', {}, 10, id='application_list'),
    # TODO: uncomment once AAP-92626 is fixed (124q/30 rows vs cutoff 15).
    # pytest.param('token-list', {}, 15, id='token_list'),
    # TODO: uncomment once AAP-92627 is fixed (94q/30 rows vs cutoff 15).
    # pytest.param('authenticatormap-list', {}, 15, id='authenticator_map_list'),
    # TODO: uncomment once AAP-92628 is fixed (37q vs public equivalent's 13q, cutoff 20).
    # pytest.param('serviceuserassignment-list', {}, 20, id='service_user_assignment_list'),
    # TODO: uncomment once AAP-92628 is fixed (45q vs public equivalent's 14q, cutoff 20).
    # pytest.param('serviceteamassignment-list', {}, 20, id='service_team_assignment_list'),
]


@pytest.mark.parametrize('url_name, query_params, max_queries', QUERY_COUNT_CASES)
def test_list_query_count_hard_cutoff(
    admin_api_client,
    _seed_large_dataset,
    _seed_oauth_applications,
    _seed_oauth_tokens,
    _seed_authenticator_maps,
    url_name,
    query_params,
    max_queries,
):
    """A request to a list endpoint should never exceed a fixed query-count
    cutoff, regardless of how many objects are returned."""
    url = get_relative_url(url_name)

    admin_api_client.get(url, query_params)  # warm up (e.g. ContentType cache)
    with CaptureQueriesContext(connection) as ctx:
        response = admin_api_client.get(url, query_params)

    assert response.status_code == 200
    # A query-count cutoff on an empty list is meaningless (AAP-88874).
    assert response.data['count'] > 0, "Expected seeded objects in the response; got an empty list."

    query_count = len(ctx.captured_queries)
    assert query_count <= max_queries, (
        f"{url}?{query_params} used {query_count} queries for " f"{response.data['count']} objects, exceeding the hard cutoff of {max_queries}."
    )
