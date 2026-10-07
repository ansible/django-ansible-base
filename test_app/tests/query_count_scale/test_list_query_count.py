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
# Failing (real N+1s found this way). Marked xfail(strict=True) rather than
# commented out: once each underlying bug is fixed, the case starts *passing*,
# strict=True turns that into a hard CI failure -- forcing someone to notice
# and remove the marker, instead of a comment nobody remembers to revisit.
QUERY_COUNT_CASES = [
    pytest.param('resource-list', {'extra_fields': 'resource_data'}, 15, id='resource_list_with_extra_fields'),
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
    pytest.param(
        'application-list',
        {},
        10,
        marks=pytest.mark.xfail(reason="AAP-92618 N+1 (access_tokens + unprefetched FK summary fields); 154q/30 rows vs cutoff 10", strict=True),
        id='application_list',
    ),
    pytest.param(
        'token-list',
        {},
        15,
        marks=pytest.mark.xfail(reason="AAP-92626 N+1 in OAuth2TokenViewSet; 124q/30 rows vs cutoff 15", strict=True),
        id='token_list',
    ),
    pytest.param(
        'authenticatormap-list',
        {},
        15,
        marks=pytest.mark.xfail(reason="AAP-92627 N+1 in AuthenticatorMapViewSet; 94q/30 rows vs cutoff 15", strict=True),
        id='authenticator_map_list',
    ),
    pytest.param(
        'serviceuserassignment-list',
        {},
        20,
        id='service_user_assignment_list',
    ),
    pytest.param(
        'serviceteamassignment-list',
        {},
        20,
        id='service_team_assignment_list',
    ),
]


@pytest.mark.parametrize('url_name, query_params, max_queries', QUERY_COUNT_CASES)
def test_list_query_count_hard_cutoff(
    session_admin_api_client,
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

    session_admin_api_client.get(url, query_params)  # warm up (e.g. ContentType cache)
    with CaptureQueriesContext(connection) as ctx:
        response = session_admin_api_client.get(url, query_params)

    assert response.status_code == 200
    # A query-count cutoff on an empty list is meaningless (AAP-88874).
    assert response.data['count'] > 0, "Expected seeded objects in the response; got an empty list."

    query_count = len(ctx.captured_queries)
    assert query_count <= max_queries, (
        f"{url}?{query_params} used {query_count} queries for " f"{response.data['count']} objects, exceeding the hard cutoff of {max_queries}."
    )
