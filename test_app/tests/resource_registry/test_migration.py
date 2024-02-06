import pytest

from ansible_base.resource_registry.models import Resource


@pytest.mark.django_db
def test_existing_resources_created_in_post_migration():
    """
    Test that resources that existed before the registry was added got
    created successfully.
    """
    assert Resource.objects.filter(name="migration resource", content_type__resource_type__name="aap.resourcemigrationtestmodel").exists()
