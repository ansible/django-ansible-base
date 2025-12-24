"""Test RBAC activity stream functionality."""

import uuid

import pytest
from crum import impersonate
from django.apps import apps
from django.contrib.auth import get_user_model

from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleTeamAssignment, RoleUserAssignment

User = get_user_model()


def verify_activity_entry_fields(entry, operation, admin_user, actor_id, role_def_id, actor_field):
    """Helper to verify activity entry has correct fields."""
    assert entry.operation == operation
    assert entry.created_by == admin_user
    assert entry.changes, f"{operation.title()} entry should have changes recorded"

    # Get the appropriate fields dict based on operation
    fields_dict = entry.changes['added_fields'] if operation == 'create' else entry.changes['removed_fields']

    # Verify required fields are present with correct values
    assert actor_field in fields_dict
    assert 'role_definition' in fields_dict
    assert str(actor_id) == fields_dict[actor_field]
    assert str(role_def_id) == fields_dict['role_definition']


@pytest.mark.skipif(not apps.is_installed('ansible_base.activitystream'), reason="Activity stream tests only run when activitystream app is installed")
@pytest.mark.django_db
def test_role_user_assignment_activity_stream_lifecycle(system_user, admin_user, organization):
    """Test role assignment create and delete both create proper activity entries."""
    # Create unique test user, role, and org with distinctive names
    test_uuid = str(uuid.uuid4())[:8]
    unique_username = f'test_rbac_user_{test_uuid}'
    unique_role_name = f'TestRole_ActivityStream_{test_uuid}'
    unique_org_name = f'TestOrg_ActivityStream_{test_uuid}'

    test_user = User.objects.create_user(username=unique_username, email=f'{unique_username}@example.com')

    # Create unique organization for this test
    from test_app.models import Organization

    test_org = Organization.objects.create(name=unique_org_name)

    ct = DABContentType.objects.get_for_model(test_org)
    role_def = RoleDefinition.objects.create(name=unique_role_name, content_type=ct)

    # Create assignment (admin assigns role to user)
    with impersonate(admin_user):
        assignment = RoleUserAssignment.objects.create(user=test_user, role_definition=role_def, content_object=test_org, created_by=admin_user)

    # Verify CREATE entry
    assert assignment.activity_stream_entries.count() == 1
    create_entry = assignment.activity_stream_entries.last()
    verify_activity_entry_fields(create_entry, 'create', admin_user, test_user.id, role_def.id, 'user')

    # Verify enhanced string representation
    entry_str = str(create_entry)
    assert "created" in entry_str.lower()
    assert str(admin_user) in entry_str

    # Delete assignment and verify DELETE entry
    assignment_id = assignment.id
    with impersonate(admin_user):
        assignment.delete()

    # Query entries directly since assignment pk=None after delete
    from django.contrib.contenttypes.models import ContentType

    from ansible_base.activitystream.models import Entry

    assignment_ct = ContentType.objects.get_for_model(RoleUserAssignment)
    assignment_entries = Entry.objects.filter(content_type=assignment_ct, object_id=str(assignment_id)).order_by('id')

    assert assignment_entries.count() == 2
    delete_entry = assignment_entries.last()
    verify_activity_entry_fields(delete_entry, 'delete', admin_user, test_user.id, role_def.id, 'user')

    # Verify enhanced string representation for delete
    delete_str = str(delete_entry)
    assert "deleted" in delete_str.lower()
    assert str(admin_user) in delete_str


@pytest.mark.skipif(not apps.is_installed('ansible_base.activitystream'), reason="Activity stream tests only run when activitystream app is installed")
@pytest.mark.django_db
def test_role_team_assignment_activity_stream(admin_user, team, organization):
    """Test team role assignment creates activity entries."""
    # Create unique role and org names for isolation
    test_uuid = str(uuid.uuid4())[:8]
    unique_role_name = f'TestTeamRole_{test_uuid}'
    unique_org_name = f'TestTeamOrg_{test_uuid}'

    # Create unique organization for this test
    from test_app.models import Organization

    test_org = Organization.objects.create(name=unique_org_name)

    ct = DABContentType.objects.get_for_model(test_org)
    role_def = RoleDefinition.objects.create(name=unique_role_name, content_type=ct)

    # Create team assignment
    with impersonate(admin_user):
        assignment = RoleTeamAssignment.objects.create(team=team, role_definition=role_def, content_object=test_org, created_by=admin_user)

    # Verify CREATE entry
    assert assignment.activity_stream_entries.count() == 1
    create_entry = assignment.activity_stream_entries.last()
    verify_activity_entry_fields(create_entry, 'create', admin_user, team.id, role_def.id, 'team')

    # Delete assignment and verify DELETE entry
    assignment_id = assignment.id
    with impersonate(admin_user):
        assignment.delete()

    # Query entries directly since assignment pk=None after delete
    from django.contrib.contenttypes.models import ContentType

    from ansible_base.activitystream.models import Entry

    assignment_ct = ContentType.objects.get_for_model(RoleTeamAssignment)
    assignment_entries = Entry.objects.filter(content_type=assignment_ct, object_id=str(assignment_id)).order_by('id')

    assert assignment_entries.count() == 2
    delete_entry = assignment_entries.last()
    verify_activity_entry_fields(delete_entry, 'delete', admin_user, team.id, role_def.id, 'team')
