from unittest import mock

import pytest
from django.test import override_settings

from ansible_base.rbac.assignment_utils import (
    AssignmentTuple,
    RemoteAssignmentFetcher,
    get_local_assignments,
    get_remote_assignments,
)
from ansible_base.resource_registry.models import Resource


def _mock_response(status_code=200, body=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.json.return_value = body or {"results": [], "next": None}
    return resp


# ---------------------------------------------------------------------------
# AssignmentTuple
# ---------------------------------------------------------------------------


def test_assignment_tuple_hashing():
    t1 = AssignmentTuple('user1', 'obj1', 'Admin', 'user')
    t2 = AssignmentTuple('user1', 'obj1', 'Admin', 'user')
    assert hash(t1) == hash(t2)
    assert {t1, t2} == {t1}


def test_assignment_tuple_equality():
    t1 = AssignmentTuple('user1', 'obj1', 'Admin', 'user')
    t2 = AssignmentTuple('user1', 'obj1', 'Admin', 'user')
    t3 = AssignmentTuple('user2', 'obj1', 'Admin', 'user')
    assert t1 == t2
    assert t1 != t3
    assert t1 != "not a tuple"
    assert t1 != 42


def test_assignment_tuple_global_vs_scoped():
    global_t = AssignmentTuple('user1', None, 'Admin', 'user')
    scoped_t = AssignmentTuple('user1', 'obj1', 'Admin', 'user')
    assert global_t != scoped_t


# ---------------------------------------------------------------------------
# AssignmentClient Protocol — structural compliance
# ---------------------------------------------------------------------------


def test_assignment_client_protocol_duck_typing():
    """A mock with the right methods can be used as an AssignmentClient."""
    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    assert hasattr(client, 'list_user_assignments')
    assert hasattr(client, 'list_team_assignments')
    assert callable(client.list_user_assignments)
    assert callable(client.list_team_assignments)


# ---------------------------------------------------------------------------
# RemoteAssignmentFetcher
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fetcher_uses_custom_page_size():
    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    ok = _mock_response()
    client.list_user_assignments.return_value = ok
    client.list_team_assignments.return_value = ok

    RemoteAssignmentFetcher(client, page_size=250).fetch()

    client.list_user_assignments.assert_called_with(filters={'page': 1, 'page_size': 250})


@pytest.mark.django_db
def test_fetcher_reads_page_size_from_settings():
    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    with override_settings(RESOURCE_SYNC_PAGE_SIZE=300):
        fetcher = RemoteAssignmentFetcher(client)
        assert fetcher.page_size == 300


@pytest.mark.django_db
def test_fetcher_incomplete_on_user_failure():
    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    client.list_user_assignments.return_value = _mock_response(status_code=500)

    result = RemoteAssignmentFetcher(client).fetch()

    assert result.is_complete is False
    client.list_team_assignments.assert_not_called()


@pytest.mark.django_db
def test_fetcher_incomplete_on_team_failure():
    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    client.list_user_assignments.return_value = _mock_response()
    client.list_team_assignments.return_value = _mock_response(status_code=500)

    result = RemoteAssignmentFetcher(client).fetch()

    assert result.is_complete is False


@pytest.mark.django_db
def test_fetcher_filters_unknown_roles():
    from ansible_base.rbac.models import RoleDefinition

    local_role = RoleDefinition.objects.create(name='KnownRole', managed=True)

    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    client.list_user_assignments.return_value = _mock_response(
        body={
            'results': [
                {'user_ansible_id': 'u1', 'role_definition': 'KnownRole', 'object_ansible_id': None},
                {'user_ansible_id': 'u2', 'role_definition': 'UnknownRole', 'object_ansible_id': None},
            ],
            'next': None,
        }
    )
    client.list_team_assignments.return_value = _mock_response()

    result = RemoteAssignmentFetcher(client).fetch()

    assert result.is_complete is True
    assert len(result.assignments) == 1
    assignment = next(iter(result.assignments))
    assert assignment.role_definition_name == local_role.name


@pytest.mark.django_db
def test_fetcher_handles_null_results():
    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    null_resp = _mock_response(body={"results": None, "next": None})
    client.list_user_assignments.return_value = null_resp
    client.list_team_assignments.return_value = null_resp

    result = get_remote_assignments(client)

    assert result.is_complete is True
    assert len(result.assignments) == 0


@pytest.mark.django_db
def test_fetcher_paginates_multiple_pages():
    from ansible_base.rbac.models import RoleDefinition

    RoleDefinition.objects.create(name='Admin', managed=True)

    client = mock.Mock(spec=['list_user_assignments', 'list_team_assignments'])
    page1 = _mock_response(
        body={
            'results': [{'user_ansible_id': 'u1', 'role_definition': 'Admin', 'object_ansible_id': None}],
            'next': 'http://example.com/page2',
        }
    )
    page2 = _mock_response(
        body={
            'results': [{'user_ansible_id': 'u2', 'role_definition': 'Admin', 'object_ansible_id': None}],
            'next': None,
        }
    )
    client.list_user_assignments.side_effect = [page1, page2]
    client.list_team_assignments.return_value = _mock_response()

    result = RemoteAssignmentFetcher(client, page_size=1).fetch()

    assert result.is_complete is True
    assert len(result.assignments) == 2


# ---------------------------------------------------------------------------
# get_local_assignments — service parameter
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_local_assignments_returns_all_when_no_service():
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from test_app.models import Organization, User

    user = User.objects.create(username='testuser', email='test@test.com')
    org = Organization.objects.create(name='Test Org')
    org_ct = DABContentType.objects.get_for_model(Organization)

    rd = RoleDefinition.objects.create(name='Org Admin', content_type=org_ct, managed=True)
    rd.give_permission(user, org)

    assignments = get_local_assignments()
    user_assignments = [a for a in assignments if a.assignment_type == 'user']
    assert len(user_assignments) >= 1


@pytest.mark.django_db
def test_get_local_assignments_filters_by_service():
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from test_app.models import Organization, User

    user = User.objects.create(username='svc_user', email='svc@test.com')
    org = Organization.objects.create(name='Svc Org')
    org_ct = DABContentType.objects.get_for_model(Organization)

    rd = RoleDefinition.objects.create(name='Svc Role', content_type=org_ct, managed=True)
    rd.give_permission(user, org)

    service_name = org_ct.service

    matching = get_local_assignments(service=service_name)
    assert any(a.role_definition_name == 'Svc Role' for a in matching)

    non_matching = get_local_assignments(service='nonexistent_service')
    assert not any(a.role_definition_name == 'Svc Role' for a in non_matching)


@pytest.mark.django_db
def test_get_local_assignments_includes_global_for_any_service():
    from ansible_base.rbac.models import RoleDefinition
    from test_app.models import User

    user = User.objects.create(username='globaluser', email='global@test.com')
    rd = RoleDefinition.objects.create(name='Global Role', managed=True)
    rd.give_global_permission(user)

    assignments = get_local_assignments(service='controller')
    assert any(a.role_definition_name == 'Global Role' for a in assignments)


@pytest.mark.django_db
def test_get_local_assignments_skips_users_without_resources():
    from ansible_base.rbac.models import RoleDefinition
    from test_app.models import User

    user = User.objects.create(username='orphanuser', email='orphan@test.com')
    user_resource = Resource.get_resource_for_object(user)

    rd = RoleDefinition.objects.create(name='Orphan Role', managed=True)
    rd.give_global_permission(user)

    user_resource.delete()

    assignments = get_local_assignments()
    assert not any(a.role_definition_name == 'Orphan Role' for a in assignments)


@pytest.mark.django_db
def test_get_local_assignments_skips_teams_without_resources():
    from ansible_base.rbac.models import RoleDefinition
    from test_app.models import Organization, Team

    org = Organization.objects.create(name='Team Org')
    team = Team.objects.create(name='Orphan Team', organization=org)
    team_resource = Resource.get_resource_for_object(team)

    rd = RoleDefinition.objects.create(name='Team Orphan Role', managed=True)
    rd.give_global_permission(team)

    team_resource.delete()

    assignments = get_local_assignments()
    assert not any(a.role_definition_name == 'Team Orphan Role' for a in assignments)


@pytest.mark.django_db
def test_get_local_assignments_object_scoped_user():
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from test_app.models import Organization, User

    user = User.objects.create(username='scopeduser', email='scoped@test.com')
    user_resource = Resource.get_resource_for_object(user)
    org = Organization.objects.create(name='Scoped Org')
    org_resource = Resource.get_resource_for_object(org)
    org_ct = DABContentType.objects.get_for_model(Organization)

    rd = RoleDefinition.objects.create(name='Scoped Admin', content_type=org_ct, managed=True)
    rd.give_permission(user, org)

    assignments = get_local_assignments()
    user_assignments = [a for a in assignments if a.role_definition_name == 'Scoped Admin']

    assert len(user_assignments) == 1
    assert user_assignments[0].actor_ansible_id == str(user_resource.ansible_id)
    assert user_assignments[0].ansible_id_or_pk == str(org_resource.ansible_id)


@pytest.mark.django_db
def test_get_local_assignments_object_scoped_team():
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from test_app.models import Organization, Team

    org = Organization.objects.create(name='Team Parent Org')
    team = Team.objects.create(name='Scoped Team', organization=org)
    team_resource = Resource.get_resource_for_object(team)
    target_org = Organization.objects.create(name='Target Org')
    target_resource = Resource.get_resource_for_object(target_org)
    org_ct = DABContentType.objects.get_for_model(Organization)

    rd = RoleDefinition.objects.create(name='Team Scoped Admin', content_type=org_ct, managed=True)
    rd.give_permission(team, target_org)

    assignments = get_local_assignments()
    team_assignments = [a for a in assignments if a.role_definition_name == 'Team Scoped Admin']

    assert len(team_assignments) == 1
    assert team_assignments[0].actor_ansible_id == str(team_resource.ansible_id)
    assert team_assignments[0].ansible_id_or_pk == str(target_resource.ansible_id)


# ---------------------------------------------------------------------------
# get_local_assignments — bulk query optimization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_local_assignments_bounded_query_count():
    """Verify that get_local_assignments uses a bounded number of queries
    regardless of assignment count (bulk resolution, not N+1).
    """
    from django.test.utils import CaptureQueriesContext

    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from test_app.models import Organization, User

    org_ct = DABContentType.objects.get_for_model(Organization)
    rd = RoleDefinition.objects.create(name='Bulk Test Role', content_type=org_ct, managed=True)

    users = []
    orgs = []
    for i in range(10):
        u = User.objects.create(username=f'bulkuser{i}', email=f'bulk{i}@test.com')
        users.append(u)
        o = Organization.objects.create(name=f'Bulk Org {i}')
        orgs.append(o)
        rd.give_permission(u, o)

    from django.db import connection

    with CaptureQueriesContext(connection) as ctx:
        assignments = get_local_assignments()

    assert any(a.role_definition_name == 'Bulk Test Role' for a in assignments)
    # Bulk resolution should use a fixed number of queries regardless of
    # assignment count:
    #   - 1 query for user assignments + 1 for team assignments
    #   - 1 bulk actor ansible_id resolve per type (user, team)
    #   - 1 bulk object ansible_id resolve per type (user, team)
    #   - 1 RoleDefinition query per type (from select_related)
    # Total ~6-8 queries. Without bulk resolution this would be 30+
    # for 10 assignments (one Resource lookup per actor + per object).
    assert len(ctx.captured_queries) < 15, f"Expected bounded queries but got {len(ctx.captured_queries)}. " "This suggests N+1 query regression."


# ---------------------------------------------------------------------------
# Backward compatibility — imports from sync.py still work
# ---------------------------------------------------------------------------


def test_backward_compat_imports():
    from ansible_base.resource_registry.tasks.sync import (  # noqa: F401,F811
        AssignmentTuple,
        RemoteAssignmentFetcher,
        RemoteAssignmentResult,
        create_local_assignment,
        delete_local_assignment,
        get_ansible_id_or_pk,
        get_content_object,
        get_local_assignments,
        get_remote_assignments,
    )
