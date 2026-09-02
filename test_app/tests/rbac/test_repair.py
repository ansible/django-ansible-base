import uuid

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType

from ansible_base.rbac.models import RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.models.content_type import DABContentType
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.backfill import backfill_object_ansible_id
from ansible_base.rbac.repair import repair_assignment_corruption
from ansible_base.resource_registry.models import Resource
from test_app.models import Organization, Team


@pytest.fixture
def org_view_rd():
    return RoleDefinition.objects.create_from_permissions(
        name='repair-test-view-org',
        permissions=['view_organization'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


# --- repair_assignment_corruption tests ---


@pytest.mark.django_db
def test_repair_deletes_corrupt_user_assignment(admin_user, organization, org_view_rd):
    """User assignments with UUID object_id under an integer-PK content type are deleted."""
    org_view_rd.give_permission(admin_user, organization)
    assignment_pk = RoleUserAssignment.objects.get(user=admin_user, role_definition=org_view_rd).pk

    # Simulate the PR-1093 corruption: a UUID ended up as object_id for an integer-PK type
    RoleUserAssignment.objects.filter(pk=assignment_pk).update(object_id=str(uuid.uuid4()))

    repair_assignment_corruption(django_apps)

    assert not RoleUserAssignment.objects.filter(pk=assignment_pk).exists()


@pytest.mark.django_db
def test_repair_deletes_corrupt_team_assignment(organization, org_view_rd):
    """Team assignments with UUID object_id under an integer-PK content type are deleted."""
    team = Team.objects.create(name='repair-corrupt-team', organization=organization)
    org_view_rd.give_permission(team, organization)
    assignment_pk = RoleTeamAssignment.objects.get(team=team, role_definition=org_view_rd).pk

    RoleTeamAssignment.objects.filter(pk=assignment_pk).update(object_id=str(uuid.uuid4()))

    repair_assignment_corruption(django_apps)

    assert not RoleTeamAssignment.objects.filter(pk=assignment_pk).exists()


@pytest.mark.django_db
def test_repair_skips_global_assignment(admin_user):
    """Global (system-wide) assignments with no object_id are not deleted or errored."""
    global_rd = RoleDefinition.objects.create_from_permissions(
        name='repair-test-global',
        permissions=['view_organization'],
        content_type=None,
    )
    global_rd.give_global_permission(admin_user)
    assignment_pk = RoleUserAssignment.objects.get(user=admin_user, role_definition=global_rd).pk

    repair_assignment_corruption(django_apps)

    assert RoleUserAssignment.objects.filter(pk=assignment_pk).exists()


@pytest.mark.django_db
def test_repair_preserves_valid_alongside_corrupt(admin_user, organization, org_view_rd):
    """Only the corrupt assignment is deleted; valid assignments for same user survive."""
    from test_app.models import Inventory

    inv_rd = RoleDefinition.objects.create_from_permissions(
        name='repair-test-inv',
        permissions=['view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )
    inv = Inventory.objects.create(name='repair-inv', organization=organization)
    org_view_rd.give_permission(admin_user, organization)
    inv_rd.give_permission(admin_user, inv)

    corrupt_pk = RoleUserAssignment.objects.get(user=admin_user, role_definition=org_view_rd).pk
    valid_pk = RoleUserAssignment.objects.get(user=admin_user, role_definition=inv_rd).pk

    RoleUserAssignment.objects.filter(pk=corrupt_pk).update(object_id=str(uuid.uuid4()))

    repair_assignment_corruption(django_apps)

    assert not RoleUserAssignment.objects.filter(pk=corrupt_pk).exists()
    assert RoleUserAssignment.objects.filter(pk=valid_pk).exists()


# --- backfill_object_ansible_id tests ---


@pytest.mark.django_db
def test_backfill_populates_user_assignment(admin_user, organization, org_view_rd):
    """Assignments with NULL object_ansible_id are populated from Resource."""
    org_view_rd.give_permission(admin_user, organization)
    RoleUserAssignment.objects.filter(user=admin_user, role_definition=org_view_rd).update(object_ansible_id=None)

    backfill_object_ansible_id(django_apps)

    assignment = RoleUserAssignment.objects.get(user=admin_user, role_definition=org_view_rd)
    org_ct = ContentType.objects.get_for_model(Organization)
    expected = Resource.objects.get(object_id=str(organization.pk), content_type=org_ct).ansible_id
    assert assignment.object_ansible_id == expected


@pytest.mark.django_db
def test_backfill_populates_team_assignment(organization, org_view_rd):
    """Team assignments are backfilled the same way as user assignments."""
    team = Team.objects.create(name='repair-test-team', organization=organization)
    org_view_rd.give_permission(team, organization)
    RoleTeamAssignment.objects.filter(team=team, role_definition=org_view_rd).update(object_ansible_id=None)

    backfill_object_ansible_id(django_apps)

    assignment = RoleTeamAssignment.objects.get(team=team, role_definition=org_view_rd)
    org_ct = ContentType.objects.get_for_model(Organization)
    expected = Resource.objects.get(object_id=str(organization.pk), content_type=org_ct).ansible_id
    assert assignment.object_ansible_id == expected


@pytest.mark.django_db
def test_backfill_does_not_overwrite_already_filled(admin_user, organization, org_view_rd):
    """Assignments with object_ansible_id already set are not re-processed."""
    org_view_rd.give_permission(admin_user, organization)
    assignment = RoleUserAssignment.objects.get(user=admin_user, role_definition=org_view_rd)
    original = assignment.object_ansible_id
    assert original is not None

    backfill_object_ansible_id(django_apps)

    assignment.refresh_from_db()
    assert assignment.object_ansible_id == original


@pytest.mark.django_db
def test_backfill_leaves_null_when_no_resource(admin_user, organization, org_view_rd):
    """Assignments whose object has no Resource row remain NULL after backfill."""
    org_view_rd.give_permission(admin_user, organization)
    assignment_pk = RoleUserAssignment.objects.get(user=admin_user, role_definition=org_view_rd).pk

    org_ct = ContentType.objects.get_for_model(Organization)
    Resource.objects.filter(object_id=str(organization.pk), content_type=org_ct).delete()
    RoleUserAssignment.objects.filter(pk=assignment_pk).update(object_ansible_id=None)

    backfill_object_ansible_id(django_apps)

    assignment = RoleUserAssignment.objects.get(pk=assignment_pk)
    assert assignment.object_ansible_id is None


@pytest.mark.django_db
def test_backfill_skips_when_resource_registry_unavailable(admin_user, organization, org_view_rd):
    """When resource_registry is not installed (LookupError), backfill returns early."""

    class NoResourceApps:
        def get_model(self, app_label, model_name=None):
            if app_label == 'dab_resource_registry':
                raise LookupError(f'No installed app with label {app_label!r}')
            return django_apps.get_model(app_label, model_name)

    org_view_rd.give_permission(admin_user, organization)
    assignment_pk = RoleUserAssignment.objects.get(user=admin_user, role_definition=org_view_rd).pk
    RoleUserAssignment.objects.filter(pk=assignment_pk).update(object_ansible_id=None)

    backfill_object_ansible_id(apps=NoResourceApps())

    assignment = RoleUserAssignment.objects.get(pk=assignment_pk)
    assert assignment.object_ansible_id is None


@pytest.mark.django_db
def test_backfill_skips_remote_content_type(admin_user, organization, org_view_rd):
    """Assignments whose DABContentType has no matching Django ContentType are left alone."""
    remote_ct = DABContentType.objects.create(
        app_label='remote_controller',
        model='job',
        pk_field_type='integer',
    )

    org_view_rd.give_permission(admin_user, organization)
    assignment_pk = RoleUserAssignment.objects.get(user=admin_user, role_definition=org_view_rd).pk

    RoleUserAssignment.objects.filter(pk=assignment_pk).update(
        content_type=remote_ct,
        object_ansible_id=None,
    )

    backfill_object_ansible_id(django_apps)

    assignment = RoleUserAssignment.objects.get(pk=assignment_pk)
    assert assignment.object_ansible_id is None
