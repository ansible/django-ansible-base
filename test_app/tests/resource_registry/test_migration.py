from unittest.mock import patch

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef, TextField
from django.db.models.functions import Cast

from ansible_base.resource_registry.apps import initialize_resources
from ansible_base.resource_registry.models import Resource
from test_app.models import Organization


@pytest.mark.django_db
def test_existing_resources_created_in_post_migration():
    """
    Test that resources that existed before the registry was added got
    created successfully.
    """
    assert Resource.objects.filter(name="migration resource", content_type__resource_type__name="aap.resourcemigrationtestmodel").exists()


@pytest.mark.django_db
def test_initialize_resources_skips_scan_but_creates_types_when_no_migrations_applied():
    """When plan=[] (no migrations applied), initialize_resources should still
    create ResourceType records (needed by post_save signal handlers) but skip
    the expensive missing-resource scan."""
    from ansible_base.resource_registry.models import ResourceType

    ResourceType.objects.all().delete()
    with patch('ansible_base.resource_registry.models.init_resource_from_object') as mock_init:
        initialize_resources(apps.get_app_config('dab_resource_registry'), plan=[])
    mock_init.assert_not_called()
    assert ResourceType.objects.count() > 0


@pytest.mark.django_db
def test_initialize_resources_runs_when_plan_has_entries():
    """initialize_resources should proceed with resource scanning when the
    plan kwarg contains migration entries."""
    with patch('ansible_base.resource_registry.registry.get_registry') as mock_registry:
        mock_registry.return_value = None
        initialize_resources(apps.get_app_config('dab_resource_registry'), plan=[('fake_migration',)])
    mock_registry.assert_called_once()


@pytest.mark.django_db
def test_initialize_resources_runs_when_plan_not_provided():
    """initialize_resources should proceed when plan kwarg is not provided
    (e.g. when called from django-admin flush)."""
    with patch('ansible_base.resource_registry.registry.get_registry') as mock_registry:
        mock_registry.return_value = None
        initialize_resources(apps.get_app_config('dab_resource_registry'))
    mock_registry.assert_called_once()


@pytest.mark.django_db
def test_missing_resources_queryset_finds_unregistered_objects():
    """The NOT EXISTS queryset correctly identifies objects that do not yet
    have a corresponding Resource entry."""
    ct = ContentType.objects.get_for_model(Organization)

    org_with_resource = Organization.objects.create(name="has-resource")
    org_without_resource = Organization.objects.create(name="no-resource")

    # post_save signal auto-creates Resource entries; remove one to simulate a gap
    Resource.objects.filter(content_type=ct, object_id=str(org_without_resource.pk)).delete()

    missing_qs = Organization.objects.annotate(pk_text=Cast('pk', TextField())).exclude(
        Exists(Resource.objects.filter(content_type=ct, object_id=OuterRef('pk_text')))
    )

    missing_ids = set(missing_qs.values_list('pk', flat=True))
    assert org_without_resource.pk in missing_ids
    assert org_with_resource.pk not in missing_ids


@pytest.mark.django_db
def test_missing_resources_queryset_returns_nothing_when_all_registered():
    """When every object has a Resource entry, the queryset returns nothing."""
    ct = ContentType.objects.get_for_model(Organization)

    orgs = [Organization.objects.create(name=f"org-{i}") for i in range(3)]
    for org in orgs:
        Resource.objects.get_or_create(content_type=ct, object_id=str(org.pk))

    missing_qs = (
        Organization.objects.filter(pk__in=[o.pk for o in orgs])
        .annotate(pk_text=Cast('pk', TextField()))
        .exclude(Exists(Resource.objects.filter(content_type=ct, object_id=OuterRef('pk_text'))))
    )

    assert missing_qs.count() == 0


@pytest.mark.django_db
def test_initialize_resources_creates_missing_resources():
    """initialize_resources creates Resource entries for objects that are missing them."""
    ct = ContentType.objects.get_for_model(Organization)
    org = Organization.objects.create(name="needs-resource")

    Resource.objects.filter(content_type=ct, object_id=str(org.pk)).delete()
    assert not Resource.objects.filter(content_type=ct, object_id=str(org.pk)).exists()

    initialize_resources(apps.get_app_config('dab_resource_registry'), plan=[('fake_migration',)])

    assert Resource.objects.filter(content_type=ct, object_id=str(org.pk)).exists()
