"""POC tests for the organization-scoped automation dashboard permissions.

These tests verify the two halves of the feature:

- ``DABPermission`` rows are created from ``Organization.Meta.permissions``.
- Organization-scoped ``RoleDefinition`` objects exist and grant the new
  permissions to a user assigned to a specific organization.
"""

import pytest

from ansible_base.rbac.models import DABPermission, RoleDefinition
from test_app.models import Organization

VIEWER_ROLE = 'Automation Dashboard Viewer'
EDITOR_ROLE = 'Automation Dashboard Editor'
VIEW_PERM = 'view_automation_dashboard_organization'
CHANGE_PERM = 'change_automation_dashboard_organization'


@pytest.mark.django_db
def test_automation_dashboard_permissions_exist():
    org_ct = DABPermission.objects.get(codename=VIEW_PERM).content_type
    assert org_ct.model_class() is Organization

    assert DABPermission.objects.filter(content_type=org_ct, codename=VIEW_PERM).exists()
    assert DABPermission.objects.filter(content_type=org_ct, codename=CHANGE_PERM).exists()


@pytest.mark.django_db
def test_automation_dashboard_role_definitions_are_org_scoped():
    org_ct = DABPermission.objects.get(codename=VIEW_PERM).content_type

    viewer = RoleDefinition.objects.get(name=VIEWER_ROLE)
    editor = RoleDefinition.objects.get(name=EDITOR_ROLE)

    assert viewer.content_type == org_ct
    assert editor.content_type == org_ct
    assert viewer.managed is True
    assert editor.managed is True

    assert set(viewer.permissions.values_list('codename', flat=True)) == {
        'view_organization',
        VIEW_PERM,
    }
    assert set(editor.permissions.values_list('codename', flat=True)) == {
        'view_organization',
        VIEW_PERM,
        CHANGE_PERM,
    }


@pytest.mark.django_db
def test_viewer_role_grants_view_only(rando, organization):
    viewer = RoleDefinition.objects.get(name=VIEWER_ROLE)
    viewer.give_permission(rando, organization)

    assert rando.has_obj_perm(organization, VIEW_PERM)
    assert not rando.has_obj_perm(organization, CHANGE_PERM)
    assert set(Organization.access_qs(rando, VIEW_PERM)) == {organization}
    assert set(Organization.access_qs(rando, CHANGE_PERM)) == set()


@pytest.mark.django_db
def test_editor_role_grants_view_and_change(rando, organization):
    editor = RoleDefinition.objects.get(name=EDITOR_ROLE)
    editor.give_permission(rando, organization)

    assert rando.has_obj_perm(organization, VIEW_PERM)
    assert rando.has_obj_perm(organization, CHANGE_PERM)
    assert set(Organization.access_qs(rando, VIEW_PERM)) == {organization}
    assert set(Organization.access_qs(rando, CHANGE_PERM)) == {organization}


@pytest.mark.django_db
def test_organization_admin_includes_automation_dashboard_permissions():
    """Organization Admin is an 'admin base' role: it gets every non-add org permission."""
    org_admin = RoleDefinition.objects.managed.org_admin
    codenames = set(org_admin.permissions.values_list('codename', flat=True))

    assert VIEW_PERM in codenames
    assert CHANGE_PERM in codenames
