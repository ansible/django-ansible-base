import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.resource_registry.apps import initialize_resources
from ansible_base.resource_registry.models import Resource, ResourceType


@pytest.mark.django_db
def test_existing_resources_created_in_post_migration():
    """
    Test that resources that existed before the registry was added got
    created successfully.
    """
    assert Resource.objects.filter(name="migration resource", content_type__resource_type__name="aap.resourcemigrationtestmodel").exists()


@pytest.mark.django_db
def test_unregistered_resource_type_skipped_on_post_migration():
    """
    Test that ResourceType entries whose model is not in the current
    RESOURCE_LIST are skipped (not crashed on) during post_migrate.

    This prevents a KeyError in initialize_resources when iterating over
    ResourceType.objects.all() and calling registry.get_config_for_model()
    for a model that has been removed from the registry between upgrades.
    """
    registered_count = ResourceType.objects.count()

    stale_ct = ContentType.objects.create(app_label="main", model="stalemodel")
    ResourceType.objects.create(content_type=stale_ct, externally_managed=False, name="awx.stalemodel")

    assert ResourceType.objects.count() == registered_count + 1

    # Should not raise KeyError
    initialize_resources(sender=None)

    # Stale entry is still present (not deleted) but was skipped without error
    assert ResourceType.objects.filter(name="awx.stalemodel").exists()
