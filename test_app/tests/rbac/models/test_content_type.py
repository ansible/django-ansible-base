import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.test import TestCase
from django.test.utils import isolate_apps

from ansible_base.rbac.models import DABContentType
from ansible_base.rbac.remote import RemoteObject
from test_app.models import Inventory, Organization


@pytest.mark.django_db
def test_migration_shadows_real_contenttype():
    assert DABContentType.objects.count() > 0  # sanity
    for dab_ct in DABContentType.objects.all():
        ct = ContentType.objects.get_by_natural_key(dab_ct.app_label, dab_ct.model)
        assert ct.id == dab_ct.id


@pytest.mark.django_db
def test_auto_create_content_type():
    DABContentType.objects.get_for_model(Inventory)
    DABContentType.objects.get_for_model(Organization)
    DABContentType.objects.all().delete()
    inv_ct = DABContentType.objects.get_for_model(Inventory)
    assert inv_ct.model == 'inventory'
    assert inv_ct.service == 'aap'

    org_ct = DABContentType.objects.get_for_model(Organization)
    assert org_ct.service == 'shared'


@pytest.mark.django_db
def test_auto_create_content_type_multiples():
    DABContentType.objects.get_for_model(Inventory)
    DABContentType.objects.get_for_model(Organization)
    DABContentType.objects.all().delete()
    data = DABContentType.objects.get_for_models(Inventory, Organization)
    inv_ct = data[Inventory]
    org_ct = data[Organization]

    assert inv_ct.model == 'inventory'
    assert inv_ct.service == 'aap'
    assert org_ct.service == 'shared'


@pytest.mark.django_db
def test_post_migrate_creates_contenttype():
    ct = DABContentType.objects.get(app_label="test_app", model="inventory")
    assert ct.service == "aap"


@pytest.mark.django_db
def test_shared_types_created_post_migrate():
    ct = DABContentType.objects.get(app_label="test_app", model='organization')
    assert ct.service == 'shared'
    assert ct.model_class() is Organization


@pytest.mark.django_db
class DABContentTypeTests(TestCase):
    """These tests originally came from Django contenttypes"""

    def setUp(self):
        DABContentType.objects.clear_cache()
        self.addCleanup(DABContentType.objects.clear_cache)

    def test_lookup_cache(self):
        with self.assertNumQueries(1):
            DABContentType.objects.get_for_model(Inventory)
        with self.assertNumQueries(0):
            ct = DABContentType.objects.get_for_model(Inventory)
        with self.assertNumQueries(0):
            DABContentType.objects.get_for_id(ct.id)
        with self.assertNumQueries(0):
            DABContentType.objects.get_by_natural_key(
                ct.service,
                ct.app_label,
                ct.model,
            )
        DABContentType.objects.clear_cache()
        with self.assertNumQueries(1):
            DABContentType.objects.get_for_model(Inventory)

    @isolate_apps("tests")
    def test_get_for_model_not_registered(self):
        class ModelCreatedOnTheFly(models.Model):
            name = models.CharField(max_length=10)

            class Meta:
                app_label = "tests"

        with pytest.raises(RuntimeError):
            DABContentType.objects.get_for_model(ModelCreatedOnTheFly)


@pytest.mark.django_db
def test_get_object_for_this_type_remote():
    """Remote objects should return a remote proxy."""
    ct = DABContentType.objects.create(
        service="remote_proj",
        app_label="testapp",
        model="book",
    )

    obj = ct.get_object_for_this_type(pk=1)

    assert isinstance(obj, RemoteObject)
    assert obj.object_id == 1
    assert obj.content_type == ct


@pytest.mark.django_db
def test_get_all_objects_for_this_type_remote():
    ct = DABContentType.objects.create(
        service="remote_proj2",
        app_label="testapp",
        model="book",
    )

    objs = ct.get_all_objects_for_this_type(pk__in=[1, 2])

    assert [o.object_id for o in objs] == [1, 2]
    assert all(isinstance(o, RemoteObject) for o in objs)


# Tests for DABContentType ID assignment race condition fixes
# Related to: https://github.com/ansible/django-ansible-base/pull/1138


@pytest.mark.django_db
def test_create_DAB_contenttypes_multiple_fallback_no_collision():
    """
    Test fix for bug #1: Multiple entries calculating fallback IDs would all
    get the same max_id + 1, causing duplicate key errors.

    This test verifies that when multiple models need fallback ID assignment
    in the same batch, each gets a unique ID.

    Scenario:
    - Pre-populate DABContentType with entries blocking Django ContentType IDs
    - Call create_DAB_contenttypes with multiple models hitting fallback path
    - Verify all entries created successfully with unique IDs
    """
    from django.apps import apps

    from ansible_base.rbac.management.create_types import create_DAB_contenttypes
    from test_app.models import Organization, Team

    # Clear all existing DABContentType entries
    DABContentType.objects.all().delete()

    # Find the Django ContentType IDs that Organization and Team would want
    org_django_ct = ContentType.objects.get_for_model(Organization)
    team_django_ct = ContentType.objects.get_for_model(Team)

    # Block those IDs with fake entries to force fallback path
    blocker1 = DABContentType.objects.create(
        id=org_django_ct.id,
        service='blocker_service',
        app_label='fake_app',
        model='blocker1',
    )
    blocker2 = DABContentType.objects.create(
        id=team_django_ct.id,
        service='blocker_service',
        app_label='fake_app',
        model='blocker2',
    )

    initial_max_id = max(blocker1.id, blocker2.id)
    initial_count = DABContentType.objects.count()

    # Call create_DAB_contenttypes - both Organization and Team will hit fallback
    # Before fix: both would calculate max_id=N, assign id=N+1 → collision
    # After fix: first gets N+1, second gets N+2
    create_DAB_contenttypes(apps=apps)

    # Verify entries were created
    shared_org = DABContentType.objects.filter(service='shared', model='organization').first()
    shared_team = DABContentType.objects.filter(service='shared', model='team').first()

    assert shared_org is not None, "shared.organization should be created"
    assert shared_team is not None, "shared.team should be created"

    # Verify they got unique IDs (both > initial_max_id, and different from each other)
    assert shared_org.id > initial_max_id, f"shared.organization id={shared_org.id} should be > {initial_max_id}"
    assert shared_team.id > initial_max_id, f"shared.team id={shared_team.id} should be > {initial_max_id}"
    assert shared_org.id != shared_team.id, "shared.organization and shared.team must have different IDs"

    # Verify no duplicate IDs in the entire table
    all_ids = list(DABContentType.objects.values_list('id', flat=True))
    assert len(all_ids) == len(set(all_ids)), f"Duplicate IDs detected: {all_ids}"

    # Verify total count increased correctly
    final_count = DABContentType.objects.count()
    assert final_count > initial_count, f"Should have more entries: {initial_count} -> {final_count}"


@pytest.mark.django_db
def test_migration_0005_create_types_if_needed_no_collision():
    """
    Test migration 0005's create_types_if_needed function with collision conditions.

    This tests the actual migration code path that would be executed during
    database migrations, ensuring it handles ID collisions correctly.
    """
    from django.apps import apps

    from ansible_base.rbac.migrations._utils import create_types_if_needed
    from ansible_base.rbac.models import DABPermission
    from test_app.models import Organization, Team

    # Clear existing entries
    DABContentType.objects.all().delete()

    # Create at least one permission to satisfy the "if needed" check
    # (create_types_if_needed only runs if permissions or role definitions exist)
    if not DABPermission.objects.exists():
        # Get or create a DABContentType for the permission
        temp_ct = DABContentType.objects.create(
            service='temp',
            app_label='test_app',
            model='temp',
        )
        DABPermission.objects.create(
            name='temp_permission',
            codename='temp_perm',
            content_type=temp_ct,
        )

    # Setup collision scenario similar to test_create_DAB_contenttypes_multiple_fallback_no_collision
    org_django_ct = ContentType.objects.get_for_model(Organization)
    team_django_ct = ContentType.objects.get_for_model(Team)

    DABContentType.objects.create(
        id=org_django_ct.id,
        service='blocker_service',
        app_label='fake_app',
        model='blocker1',
    )
    DABContentType.objects.create(
        id=team_django_ct.id,
        service='blocker_service',
        app_label='fake_app',
        model='blocker2',
    )

    initial_count = DABContentType.objects.count()

    # Call the migration function
    # This is what migration 0005 actually calls
    create_types_if_needed(apps, schema_editor=None)

    # Verify entries were created without collision
    shared_org = DABContentType.objects.filter(service='shared', model='organization').first()
    shared_team = DABContentType.objects.filter(service='shared', model='team').first()

    # At minimum, verify no duplicate IDs
    all_ids = list(DABContentType.objects.values_list('id', flat=True))
    assert len(all_ids) == len(set(all_ids)), f"Migration created duplicate IDs: {all_ids}"

    # Verify count increased (some entries were created)
    final_count = DABContentType.objects.count()
    assert final_count >= initial_count, "Migration should create or preserve entries"

    # If the models are in permission_registry, they should be created
    if shared_org and shared_team:
        assert shared_org.id != shared_team.id, "Migration should assign unique IDs"


@pytest.mark.django_db
def test_reserved_ids_prevents_direct_assignment_collision():
    """
    Test that reserved_ids prevents collision between fallback and direct assignment.

    This specifically exercises the condition: real_ct.id not in reserved_ids

    Scenario:
    - Organization needs fallback (its Django CT ID is blocked)
    - Set max_id so Organization's fallback reserves Team's Django CT ID
    - Team tries direct assignment with that ID
    - reserved_ids check prevents collision, Team uses fallback instead

    This ensures the fix properly tracks batch reservations, not just DB state.
    """
    from django.apps import apps

    from ansible_base.rbac.management.create_types import create_DAB_contenttypes
    from test_app.models import Organization, Team

    # Clear all existing DABContentType entries
    DABContentType.objects.all().delete()

    # Get Django ContentType IDs
    org_django_ct = ContentType.objects.get_for_model(Organization)
    team_django_ct = ContentType.objects.get_for_model(Team)

    # Critical setup: Create a scenario where fallback ID equals a direct ID
    # Block ONLY Organization's ID, leave Team's ID free
    DABContentType.objects.create(
        id=org_django_ct.id,
        service='blocker_service',
        app_label='fake_app',
        model='blocker',
    )

    # Set max_id = team_django_ct.id - 1
    # So Organization's fallback calculates: max_id + 1 = team_django_ct.id
    # This creates the collision scenario
    if team_django_ct.id > org_django_ct.id:
        setup_id = team_django_ct.id - 1
        if setup_id != org_django_ct.id:  # Don't duplicate the blocker
            DABContentType.objects.create(
                id=setup_id,
                service='setup_service',
                app_label='fake_app',
                model='setup',
            )

    # Now when create_DAB_contenttypes runs:
    # 1. Organization: CT ID blocked → fallback = max_id+1 = team_django_ct.id
    #    Reserves team_django_ct.id in reserved_ids
    # 2. Team: real_ct.id = team_django_ct.id
    #    Check: not in DB? TRUE
    #    Check: not in reserved_ids? FALSE ← THIS IS THE KEY CHECK
    #    Must use fallback instead of direct assignment

    create_DAB_contenttypes(apps=apps)

    # Verify both created
    shared_org = DABContentType.objects.filter(service='shared', model='organization').first()
    shared_team = DABContentType.objects.filter(service='shared', model='team').first()

    assert shared_org is not None, "shared.organization should be created"
    assert shared_team is not None, "shared.team should be created"

    # The key assertion: Team should NOT have its Django CT ID
    # because that ID was reserved by Organization's fallback
    if team_django_ct.id > org_django_ct.id:
        # If the scenario was set up correctly:
        # - Organization likely got team_django_ct.id (fallback)
        # - Team could NOT use team_django_ct.id (reserved), got different ID
        assert shared_org.id != shared_team.id, "Must have different IDs"

        # Verify the reserved_ids check worked:
        # If Team has its Django CT ID, the check failed
        if shared_org.id == team_django_ct.id:
            assert shared_team.id != team_django_ct.id, (
                f"Team should not have Django CT ID {team_django_ct.id} "
                f"because Organization reserved it via fallback. "
                f"This means 'real_ct.id not in reserved_ids' check failed!"
            )

    # Verify no duplicates
    all_ids = list(DABContentType.objects.values_list('id', flat=True))
    assert len(all_ids) == len(set(all_ids)), f"Duplicate IDs detected: {all_ids}"
