"""Query-count regression coverage for list endpoints.

Requests each endpoint at page_size=1/10/100 and asserts the query count
stays flat -- a growing count as the page grows is the signature of an N+1,
caught directly without a hand-picked per-endpoint cutoff.

This includes the RBAC-assignment-list endpoints: `BaseAssignmentViewSet`'s
permission filter runs a fixed number of queries regardless of page size or
total assignment volume, so they behave like any other endpoint here.

Uses the shared dataset from this directory's `conftest.py`. No
`@pytest.mark.django_db` marker needed -- see that module's docstring.
"""

import pytest

from ansible_base.lib.testing.query_counts import assert_query_count_flat
from ansible_base.lib.utils.response import get_relative_url

# Endpoints to sweep across page sizes. Add new list endpoints here by default.
PAGE_SIZE_SWEEP_CASES = [
    # Higher tolerance, not a weaker check: the content_object prefetch fix
    # batches once per distinct content type on the page (bounded by the ~9
    # registered resource types here), not once per row.
    pytest.param('resource-list', {'extra_fields': 'resource_data'}, dict(max_query_delta=8), id='resource_list_with_extra_fields'),
    pytest.param('resource-list', {}, {}, id='resource_list_without_extra_fields'),
    pytest.param('organization-list', {}, {}, id='organization_list'),
    pytest.param('team-list', {}, {}, id='team_list'),
    pytest.param('user-list', {}, {}, id='user_list'),
    pytest.param('inventory-list', {}, {}, id='inventory_list'),
    pytest.param('roledefinition-list', {}, {}, id='role_definition_list'),
    pytest.param('resourcetype-list', {}, {}, id='resource_type_list'),
    pytest.param('dabcontenttype-list', {}, {}, id='dab_content_type_list'),
    pytest.param('dabpermission-list', {}, {}, id='dab_permission_list'),
    pytest.param('activitystream-list', {}, {}, id='activity_stream_list'),
    pytest.param('aap_flags_states-list', {}, {}, id='aap_flags_states_list'),
    pytest.param('roleuserassignment-list', {}, {}, id='role_user_assignment_list'),
    pytest.param('roleteamassignment-list', {}, {}, id='role_team_assignment_list'),
    pytest.param('serviceuserassignment-list', {}, {}, id='service_user_assignment_list'),
    pytest.param('serviceteamassignment-list', {}, {}, id='service_team_assignment_list'),
    # Failing (real N+1s). xfail(strict=True) so a fix flips this to a hard
    # CI failure (forcing marker removal) instead of a stale comment.
    pytest.param(
        'application-list',
        {},
        {},
        marks=pytest.mark.xfail(reason="N+1: access_tokens + unprefetched FK summary fields", strict=True),
        id='application_list',
    ),
    pytest.param(
        'token-list',
        {},
        {},
        marks=pytest.mark.xfail(reason="N+1 in OAuth2TokenViewSet", strict=True),
        id='token_list',
    ),
    pytest.param(
        'authenticatormap-list',
        {},
        {},
        marks=pytest.mark.xfail(reason="N+1 in AuthenticatorMapViewSet", strict=True),
        id='authenticator_map_list',
    ),
    pytest.param(
        'authenticator-list',
        {},
        {},
        marks=pytest.mark.xfail(reason="N+1: missing select_related for created_by/modified_by", strict=True),
        id='authenticator_list',
    ),
]


@pytest.mark.parametrize('url_name, query_params, sweep_kwargs', PAGE_SIZE_SWEEP_CASES)
def test_list_query_count_flat_across_page_size(
    session_admin_api_client,
    _seed_large_dataset,
    _seed_oauth_applications,
    _seed_oauth_tokens,
    _seed_authenticator_maps,
    _seed_authenticators,
    url_name,
    query_params,
    sweep_kwargs,
):
    """A request to a list endpoint should use roughly the same number of
    queries whether it returns 1, 10, or 100 objects -- a growing count as
    page size increases is the signature of an N+1."""
    url = get_relative_url(url_name)
    assert_query_count_flat(session_admin_api_client, url, query_params, **sweep_kwargs)
