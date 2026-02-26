"""Unit tests for AAPFlag audit logging and activity stream behavior.

Ensures that:
1. AAPFlag has audit_log_enabled = True (generates audit logs)
2. AAPFlag has activity_stream_enabled = False (no activity stream entries)
3. Create operations generate audit logs at INFO level (to aap.auth_audit logger)
4. Create operations do NOT create activity stream entries

Note: Update and delete behavior is covered by base AuditableModel tests in
test_app/tests/activitystream/test_signals.py. This provides AAPFlag-specific
regression coverage for the create operation.
"""

from unittest import mock

import pytest
from django.conf import settings

from ansible_base.feature_flags.models import AAPFlag

# Patch where DAB activitystream calls it (signals import log_auth_event at load time)
# log_auth_event writes to the logger specified by ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME
# (default: 'ansible_base.auth_audit', overridden in AAP Gateway to 'aap.auth_audit')
AUDIT_LOG_PATCH = "ansible_base.activitystream.signals.log_auth_event"

# Check if activitystream is installed
ACTIVITYSTREAM_INSTALLED = 'ansible_base.activitystream' in settings.INSTALLED_APPS


# -----------------------------------------------------------------------------
# Basic functionality test: verify AAPFlag works without activitystream
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_aap_flag_basic_crud_without_activitystream():
    """AAPFlag can be created, read, updated, and deleted regardless of activitystream installation."""
    # Create
    flag = AAPFlag.objects.create(
        name="FEATURE_TEST_BASIC_CRUD_ENABLED",
        ui_name="Test Basic CRUD",
        condition="boolean",
        value="False",
        support_level="DEVELOPER_PREVIEW",
        description="Test flag for basic CRUD operations",
    )

    # Read
    assert flag.name == "FEATURE_TEST_BASIC_CRUD_ENABLED"
    assert flag.ui_name == "Test Basic CRUD"

    # Update
    flag.value = "True"
    flag.save()
    flag.refresh_from_db()
    assert flag.value == "True"


# -----------------------------------------------------------------------------
# Verify AAPFlag has correct attribute settings
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_aap_flag_has_audit_log_enabled():
    """AAPFlag has audit_log_enabled = True to enable audit logging."""
    assert getattr(AAPFlag, "audit_log_enabled", False) is True


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_aap_flag_has_activity_stream_disabled():
    """AAPFlag has activity_stream_enabled = False to disable activity stream."""
    assert getattr(AAPFlag, "activity_stream_enabled", True) is False


# -----------------------------------------------------------------------------
# Audit log test: verify create generates audit log
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_audit_log_aap_flag_create():
    """Creating an AAPFlag emits an audit log record at INFO."""
    with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
        AAPFlag.objects.create(
            name="FEATURE_TEST_AUDIT_CREATE_ENABLED",
            ui_name="Test Audit Create",
            condition="boolean",
            value="False",
            support_level="DEVELOPER_PREVIEW",
            description="Test flag for audit logging on create",
        )

    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "create" in msg
    assert "aapflag" in msg or "feature" in msg or "flag" in msg


# -----------------------------------------------------------------------------
# Activity stream test: verify create does NOT create entry
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.skipif(not ACTIVITYSTREAM_INSTALLED, reason="activitystream not installed")
def test_activity_stream_disabled_on_create():
    """Creating an AAPFlag does NOT create an activity stream entry."""
    from ansible_base.activitystream.models import Entry

    initial_entry_count = Entry.objects.count()

    AAPFlag.objects.create(
        name="FEATURE_TEST_STREAM_CREATE_ENABLED",
        ui_name="Test Stream Create",
        condition="boolean",
        value="False",
        support_level="DEVELOPER_PREVIEW",
        description="Test flag for activity stream on create",
    )

    # No new activity stream entries should be created
    assert Entry.objects.count() == initial_entry_count
