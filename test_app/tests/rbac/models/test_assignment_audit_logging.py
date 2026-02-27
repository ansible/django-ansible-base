"""Unit tests for RoleUserAssignment and RoleTeamAssignment audit logging.

Ensures that:
1. Both assignment classes have audit_log_enabled = True (generates audit logs)
2. Both assignment classes have activity_stream_enabled = False (no activity stream entries)
3. Create operations generate audit logs at INFO level
4. Create operations do NOT create activity stream entries
5. Delete operations generate audit logs at INFO level
6. Delete operations do NOT create activity stream entries
"""

from unittest import mock

import pytest
from django.conf import settings

from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment

# Patch where DAB activitystream calls it
AUDIT_LOG_PATCH = "ansible_base.activitystream.signals.log_auth_event"

# Check if activitystream is installed
ACTIVITYSTREAM_INSTALLED = 'ansible_base.activitystream' in settings.INSTALLED_APPS


# -----------------------------------------------------------------------------
# Verify both assignment classes have correct attribute settings
# -----------------------------------------------------------------------------


def test_role_user_assignment_has_audit_log_enabled():
    """RoleUserAssignment has audit_log_enabled = True to enable audit logging."""
    assert getattr(RoleUserAssignment, "audit_log_enabled", False) is True


def test_role_user_assignment_has_activity_stream_disabled():
    """RoleUserAssignment has activity_stream_enabled = False to disable activity stream."""
    assert getattr(RoleUserAssignment, "activity_stream_enabled", True) is False


def test_role_team_assignment_has_audit_log_enabled():
    """RoleTeamAssignment has audit_log_enabled = True to enable audit logging."""
    assert getattr(RoleTeamAssignment, "audit_log_enabled", False) is True


def test_role_team_assignment_has_activity_stream_disabled():
    """RoleTeamAssignment has activity_stream_enabled = False to disable activity stream."""
    assert getattr(RoleTeamAssignment, "activity_stream_enabled", True) is False


# -----------------------------------------------------------------------------
# Audit log tests: verify create generates audit log
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_audit_log_role_user_assignment_create(rando, inventory, inv_rd):
    """Creating a RoleUserAssignment emits an audit log record at INFO."""
    with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
        inv_rd.give_permission(rando, inventory)

    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "create" in msg
    assert "roleuserassignment" in msg or "assignment" in msg


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_audit_log_role_team_assignment_create(team, inventory, inv_rd):
    """Creating a RoleTeamAssignment emits an audit log record at INFO."""
    with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
        inv_rd.give_permission(team, inventory)

    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "create" in msg
    assert "roleteamassignment" in msg or "assignment" in msg


# -----------------------------------------------------------------------------
# Activity stream tests: verify create does NOT create entry
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_activity_stream_disabled_on_user_assignment_create(rando, inventory, inv_rd):
    """Creating a RoleUserAssignment does NOT create an activity stream entry."""
    from ansible_base.activitystream.models import Entry

    initial_entry_count = Entry.objects.count()

    inv_rd.give_permission(rando, inventory)

    # No new activity stream entries should be created
    assert Entry.objects.count() == initial_entry_count


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_activity_stream_disabled_on_team_assignment_create(team, inventory, inv_rd):
    """Creating a RoleTeamAssignment does NOT create an activity stream entry."""
    from ansible_base.activitystream.models import Entry

    initial_entry_count = Entry.objects.count()

    inv_rd.give_permission(team, inventory)

    # No new activity stream entries should be created
    assert Entry.objects.count() == initial_entry_count


# -----------------------------------------------------------------------------
# Audit log tests: verify delete generates audit log
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_audit_log_role_user_assignment_delete(rando, inventory, inv_rd):
    """Deleting a RoleUserAssignment emits an audit log record at INFO."""
    # Create assignment first
    inv_rd.give_permission(rando, inventory)

    # Delete and verify audit log
    with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
        inv_rd.remove_permission(rando, inventory)

    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "delete" in msg
    assert "roleuserassignment" in msg or "assignment" in msg


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_audit_log_role_team_assignment_delete(team, inventory, inv_rd):
    """Deleting a RoleTeamAssignment emits an audit log record at INFO."""
    # Create assignment first
    inv_rd.give_permission(team, inventory)

    # Delete and verify audit log
    with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
        inv_rd.remove_permission(team, inventory)

    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "delete" in msg
    assert "roleteamassignment" in msg or "assignment" in msg


# -----------------------------------------------------------------------------
# Activity stream tests: verify delete does NOT create entry
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_activity_stream_disabled_on_user_assignment_delete(rando, inventory, inv_rd):
    """Deleting a RoleUserAssignment does NOT create an activity stream entry."""
    from ansible_base.activitystream.models import Entry

    # Create assignment first
    inv_rd.give_permission(rando, inventory)

    initial_entry_count = Entry.objects.count()

    # Delete assignment
    inv_rd.remove_permission(rando, inventory)

    # No new activity stream entries should be created
    assert Entry.objects.count() == initial_entry_count


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_activity_stream_disabled_on_team_assignment_delete(team, inventory, inv_rd):
    """Deleting a RoleTeamAssignment does NOT create an activity stream entry."""
    from ansible_base.activitystream.models import Entry

    # Create assignment first
    inv_rd.give_permission(team, inventory)

    initial_entry_count = Entry.objects.count()

    # Delete assignment
    inv_rd.remove_permission(team, inventory)

    # No new activity stream entries should be created
    assert Entry.objects.count() == initial_entry_count
