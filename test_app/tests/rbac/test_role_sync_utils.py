from unittest import mock

import pytest

from ansible_base.rbac.role_sync_utils import (
    _SKIP,
    AssignmentTuple,
    _collect_assignment_tuples,
    _resolve_object_ansible_id,
    get_content_object,
    get_local_assignments,
)
from ansible_base.resource_registry.models import Resource

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
# get_content_object — ValueError guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_content_object_rejects_none_content_type():
    """get_content_object raises ValueError when role_definition.content_type is None."""
    rd = mock.Mock(content_type=None)
    at = AssignmentTuple('user1', 'obj1', 'Admin', 'user')
    with pytest.raises(ValueError, match="content_type"):
        get_content_object(rd, at)


# ---------------------------------------------------------------------------
# _resolve_object_ansible_id
# ---------------------------------------------------------------------------


def test_resolve_object_ansible_id_global_assignment():
    """Global assignments (no object_id / no content_type) return None."""
    assignment = mock.Mock(object_id=None, content_type=None)
    assert _resolve_object_ansible_id(assignment, {}) is None


def test_resolve_object_ansible_id_non_org_team():
    """Non-org/team types return the raw object_id."""
    ct = mock.Mock(model='inventory')
    assignment = mock.Mock(object_id='42', content_type=ct)
    assert _resolve_object_ansible_id(assignment, {}) == '42'


def test_resolve_object_ansible_id_org_resolved():
    """Org/team types return the resolved ansible_id from the map."""
    ct = mock.Mock(model='organization')
    assignment = mock.Mock(object_id='7', content_type=ct)
    object_map = {('7', 'organization'): 'resolved-uuid'}
    assert _resolve_object_ansible_id(assignment, object_map) == 'resolved-uuid'


def test_resolve_object_ansible_id_org_missing():
    """Missing org/team resource returns _SKIP sentinel."""
    ct = mock.Mock(model='organization')
    assignment = mock.Mock(object_id='999', content_type=ct)
    assert _resolve_object_ansible_id(assignment, {}) is _SKIP


# ---------------------------------------------------------------------------
# _collect_assignment_tuples
# ---------------------------------------------------------------------------


def test_collect_assignment_tuples_empty_list():
    """Empty input returns an empty set."""
    assert _collect_assignment_tuples([], 'user', 'user') == set()


@pytest.mark.django_db
def test_collect_assignment_tuples_skips_missing_actors():
    """Assignments whose actor has no Resource entry are skipped."""
    from ansible_base.rbac.models import RoleDefinition
    from test_app.models import User

    user = User.objects.create(username='collect_user', email='collect@test.com')
    rd = RoleDefinition.objects.create(name='Collect Role', managed=True)
    rd.give_global_permission(user)

    from ansible_base.rbac.models.role import RoleUserAssignment

    assignment_list = list(RoleUserAssignment.objects.select_related('user', 'role_definition', 'content_type').filter(role_definition=rd))

    Resource.get_resource_for_object(user).delete()

    result = _collect_assignment_tuples(assignment_list, 'user', 'user')
    assert not any(a.role_definition_name == 'Collect Role' for a in result)


@pytest.mark.django_db
def test_collect_assignment_tuples_skips_missing_object_resource():
    """Assignments with org/team objects lacking a Resource entry are skipped."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from test_app.models import Organization, User

    user = User.objects.create(username='objskip_user', email='objskip@test.com')
    org = Organization.objects.create(name='ObjSkip Org')
    org_ct = DABContentType.objects.get_for_model(Organization)

    rd = RoleDefinition.objects.create(name='ObjSkip Role', content_type=org_ct, managed=True)
    rd.give_permission(user, org)

    from ansible_base.rbac.models.role import RoleUserAssignment

    assignment_list = list(RoleUserAssignment.objects.select_related('user', 'role_definition', 'content_type').filter(role_definition=rd))

    Resource.get_resource_for_object(org).delete()

    result = _collect_assignment_tuples(assignment_list, 'user', 'user')
    assert not any(a.role_definition_name == 'ObjSkip Role' for a in result)


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

    for i in range(10):
        u = User.objects.create(username=f'bulkuser{i}', email=f'bulk{i}@test.com')
        o = Organization.objects.create(name=f'Bulk Org {i}')
        rd.give_permission(u, o)

    from django.db import connection

    with CaptureQueriesContext(connection) as ctx:
        assignments = get_local_assignments()

    assert any(a.role_definition_name == 'Bulk Test Role' for a in assignments)
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
