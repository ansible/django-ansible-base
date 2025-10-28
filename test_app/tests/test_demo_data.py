import os
from unittest.mock import patch

import pytest

from ansible_base.rbac.models import RoleDefinition
from test_app.management.commands.create_demo_data import Command
from test_app.models import Organization


@pytest.mark.django_db
def test_demo_data_with_existing_data(admin_user):
    Organization.objects.create(name='stub')
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').exists()
    assert Organization.objects.filter(name='stub').exists()


@pytest.mark.django_db
def test_demo_data_create_data(admin_user):
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').exists()


@pytest.mark.django_db
def test_demo_data_idempotent(admin_user):
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').exists()
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').count() == 1


@pytest.mark.django_db
@patch.dict(os.environ, {'LARGE': '1'})
def test_demo_data_large_mode_creates_roledefinitions(admin_user):
    """
    Test that when LARGE=1 environment variable is set, the create_demo_data command
    creates a large number of RoleDefinitions with permissions as specified in settings.
    """
    # Verify no large data exists initially
    assert not Organization.objects.filter(name__startswith='large_').exists()
    assert not RoleDefinition.objects.filter(name__startswith='Large Role Definition').exists()

    # Run the command with LARGE environment variable set
    Command().handle()

    # Verify standard demo data was created
    assert Organization.objects.filter(name='AWX_community').exists()

    # Verify large datasets were created as specified in DEMO_DATA_COUNTS
    from django.conf import settings

    expected_rd_count = settings.DEMO_DATA_COUNTS['roledefinition']

    # Check that the expected number of RoleDefinitions were created
    large_role_definitions = RoleDefinition.objects.filter(name__startswith='Large Role Definition')
    assert large_role_definitions.count() == expected_rd_count

    # Verify that RoleDefinitions have permissions attached
    sample_rd = large_role_definitions.first()
    assert sample_rd.permissions.count() == 2  # Each RD should have 2 permissions

    # Verify permission structure
    permissions = sample_rd.permissions.all()
    permission_codenames = [p.codename for p in permissions]
    assert any('view_large_role_' in codename for codename in permission_codenames)
    assert any('edit_large_role_' in codename for codename in permission_codenames)

    # Verify that RoleDefinitions have the correct content_type (Organization)
    assert sample_rd.content_type is not None
    assert sample_rd.content_type.model == 'organization'

    # Verify that over 25 permissions were assigned to users and teams
    from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment

    # Count user permissions (RoleUserAssignment records)
    user_assignments = RoleUserAssignment.objects.count()
    assert user_assignments >= 25, f"Expected at least 25 user role assignments, got {user_assignments}"

    # Count team permissions (RoleTeamAssignment records)
    team_assignments = RoleTeamAssignment.objects.count()
    assert team_assignments >= 25, f"Expected at least 25 team role assignments, got {team_assignments}"
