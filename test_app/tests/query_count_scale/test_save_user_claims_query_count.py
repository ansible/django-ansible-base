"""Hard-cutoff query-count benchmarks for the save_user_claims code path (AAP-89246).

save_user_claims (ansible_base/rbac/claims.py) is the JWT-claims write path,
called on every JWT-authenticated request -- not an HTTP list endpoint, so it
isn't reachable by test_list_query_count.py's viewset sweep (AAP-88876). Same
hard-cutoff philosophy applied to a Python code path instead of a paginated
response: build a claims payload of a given shape/size against the shared
AAP-88875 dataset, call save_user_claims once, and assert the query count
stays under a fixed cutoff -- plus a functional-correctness check that the
resulting RoleUserAssignment state actually matches what was requested, since
save_user_claims deliberately skips post_save signals
(fire_signals_on_create=False) for speed and could silently produce wrong
state while still looking fast.

One function, parametrized over `CLAIMS_QUERY_COUNT_CASES`. Add new claims
shapes as list entries here, not new test functions.

Uses the shared dataset from this directory's conftest.py. No
`@pytest.mark.django_db` marker needed -- see that module's docstring.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.rbac.claims import get_role_definition, save_user_claims
from ansible_base.rbac.models import RoleUserAssignment
from test_app.models import Organization, Team


def _org_admin_claims(n, name_prefix):
    """N Organization Admin grants against N distinct, already-synced seeded orgs."""
    orgs = list(Organization.objects.filter(name__startswith='large_organization_').order_by('id')[:n])
    assert len(orgs) == n, f"expected {n} seeded orgs, got {len(orgs)} -- is the AAP-88875 dataset seeded?"
    objects = {'organization': [], 'team': []}
    object_roles = {'Organization Admin': {'content_type': 'organization', 'objects': []}}
    for i, org in enumerate(orgs):
        objects['organization'].append({'ansible_id': str(org.resource.ansible_id), 'name': f'{name_prefix}_{org.name}'})
        object_roles['Organization Admin']['objects'].append(i)
    return objects, object_roles


def _team_member_claims(n, name_prefix):
    """N Team Member grants against N distinct, already-synced seeded teams."""
    teams = list(Team.objects.filter(name__startswith='large_team_').select_related('organization').order_by('id')[:n])
    assert len(teams) == n, f"expected {n} seeded teams, got {len(teams)} -- is the AAP-88875 dataset seeded?"
    objects = {'organization': [], 'team': []}
    object_roles = {'Team Member': {'content_type': 'team', 'objects': []}}
    org_index = {}
    for i, team in enumerate(teams):
        org_aid = str(team.organization.resource.ansible_id)
        if org_aid not in org_index:
            org_index[org_aid] = len(objects['organization'])
            objects['organization'].append({'ansible_id': org_aid, 'name': f'{name_prefix}_{team.organization.name}'})
        objects['team'].append({'ansible_id': str(team.resource.ansible_id), 'name': f'{name_prefix}_{team.name}', 'org': org_index[org_aid]})
        object_roles['Team Member']['objects'].append(i)
    return objects, object_roles


def _mixed_claims(n, name_prefix):
    """A realistic combined payload: half org-level, half team-mediated grants in one call."""
    org_objects, org_roles = _org_admin_claims(n // 2, f'{name_prefix}_org')
    team_objects, team_roles = _team_member_claims(n // 2, f'{name_prefix}_team')
    offset = len(org_objects['organization'])
    for team in team_objects['team']:
        team['org'] += offset
    objects = {
        'organization': org_objects['organization'] + team_objects['organization'],
        'team': team_objects['team'],
    }
    object_roles = {**org_roles, **team_roles}
    return objects, object_roles


def _new_org_stub_claims(n, name_prefix):
    """N Organization Admin grants against N orgs that don't exist locally yet --
    forces save_user_claims's create-resource branch (get_or_create_resource
    creating a brand new Organization from a remote ansible_id), instead of
    resolving an already-synced one."""
    objects = {'organization': [], 'team': []}
    object_roles = {'Organization Admin': {'content_type': 'organization', 'objects': []}}
    for i in range(n):
        ansible_id = str(uuid.uuid4())
        # Name embeds the ansible_id so reruns against a --reuse-db database never collide
        # on Organization.name's unique constraint (each run uses fresh random ansible_ids).
        objects['organization'].append({'ansible_id': ansible_id, 'name': f'{name_prefix}_remote_org_{ansible_id}'})
        object_roles['Organization Admin']['objects'].append(i)
    return objects, object_roles


EMPTY_CLAIMS = ({'organization': [], 'team': []}, {})

# Measured against the AAP-88875 shared dataset (~150 orgs/43 teams), N=30 grants
# per case, save_user_claims called once per case (not a 2-vs-30 delta -- a
# single hard cutoff, since the claims payload size is unbounded by pagination
# unlike an HTTP list endpoint).
#
# All five cases currently FAIL -- confirmed real N+1: save_user_claims's own
# "Pass 1: resolve resources" loop (get_or_create_resource) does an unbatched,
# per-grant Resource lookup, and downstream permission recomputation also
# appears to scale per grant instead of being fully batched across the whole
# payload. Filed as AAP-94782 (Related-linked to epic AAP-88874), xfail(strict=True)
# so the marker must be removed once AAP-94782 is fixed -- see that ticket for
# full measured evidence.
CLAIMS_QUERY_COUNT_CASES = [
    pytest.param(
        None,
        _org_admin_claims,
        30,
        20,
        marks=pytest.mark.xfail(reason="AAP-94782 save_user_claims N+1; 619q for 30 org-admin grants vs cutoff 20", strict=True),
        id='org_level',
    ),
    pytest.param(
        None,
        _team_member_claims,
        30,
        20,
        marks=pytest.mark.xfail(reason="AAP-94782 save_user_claims N+1; 169q for 30 team-member grants vs cutoff 20", strict=True),
        id='team_mediated',
    ),
    pytest.param(
        None,
        _mixed_claims,
        30,
        20,
        marks=pytest.mark.xfail(reason="AAP-94782 save_user_claims N+1; 397q for 15+15 mixed org/team grants vs cutoff 20", strict=True),
        id='mixed',
    ),
    pytest.param(
        None,
        _new_org_stub_claims,
        30,
        20,
        marks=pytest.mark.xfail(reason="AAP-94782 save_user_claims N+1; 948q for 30 new-org-stub grants vs cutoff 20", strict=True),
        id='new_org_stub',
    ),
    pytest.param(
        _org_admin_claims,
        None,  # action claims is EMPTY_CLAIMS -- revoke everything granted by setup
        30,
        20,
        marks=pytest.mark.xfail(reason="AAP-94782 save_user_claims N+1; 615q to revoke 30 org-admin grants vs cutoff 20", strict=True),
        id='stale_removal',
    ),
]


@pytest.mark.parametrize('setup_builder, action_builder, n, max_queries', CLAIMS_QUERY_COUNT_CASES)
def test_save_user_claims_query_count_hard_cutoff(_seed_large_dataset, setup_builder, action_builder, n, max_queries, request):
    """A single save_user_claims call should never exceed a fixed query-count
    cutoff, regardless of how many grants are in the claims payload -- and the
    resulting assignment state must exactly match what was requested, despite
    fire_signals_on_create=False skipping post_save signals on the fast path."""
    case_id = request.node.callspec.id
    user = get_user_model().objects.get_or_create(username=f'claims_query_count_{case_id}')[0]
    get_role_definition('Organization Admin')
    get_role_definition('Team Member')

    if setup_builder is not None:
        # e.g. stale_removal: grant first (unmeasured), then measure the revoke call.
        setup_objects, setup_object_roles = setup_builder(n, f'{case_id}_setup')
        save_user_claims(user, objects=setup_objects, object_roles=setup_object_roles, global_roles=[])
        action_objects, action_object_roles = EMPTY_CLAIMS
        expected_role_names = []
    else:
        action_objects, action_object_roles = action_builder(n, case_id)
        expected_role_names = list(action_object_roles.keys())

    with CaptureQueriesContext(connection) as ctx:
        save_user_claims(user, objects=action_objects, object_roles=action_object_roles, global_roles=[])

    # Functional correctness first: the resulting assignment state must exactly
    # match what was requested, even though fire_signals_on_create=False skips
    # post_save signals on the fast path (AAP-89246).
    actual_role_names = set(RoleUserAssignment.objects.filter(user=user, content_type__isnull=False).values_list('role_definition__name', flat=True).distinct())
    assert actual_role_names == set(
        expected_role_names
    ), f"After save_user_claims, user has roles {sorted(actual_role_names)}, expected {sorted(expected_role_names)}."
    if not expected_role_names:
        assert not RoleUserAssignment.objects.filter(user=user, content_type__isnull=False).exists(), "Stale assignments were not removed."
    else:
        total_assignments = RoleUserAssignment.objects.filter(user=user, content_type__isnull=False).count()
        assert total_assignments == n, f"Expected {n} object-role assignments after save_user_claims, got {total_assignments}."

    query_count = len(ctx.captured_queries)
    assert (
        query_count <= max_queries
    ), f"save_user_claims used {query_count} queries for a {n}-grant '{case_id}' payload, exceeding the hard cutoff of {max_queries}."
