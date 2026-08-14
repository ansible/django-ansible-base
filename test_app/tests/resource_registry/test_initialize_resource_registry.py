from unittest import mock

import pytest
from django.core.management import call_command

from ansible_base.resource_registry.models import Resource, ResourceType
from ansible_base.resource_registry.registry import get_registry


@pytest.mark.django_db
def test_initialize_resource_registry_populates_empty_registry(user):
    """Command creates ResourceType and Resource records when registry is empty."""
    ResourceType.objects.all().delete()
    Resource.objects.all().delete()

    assert ResourceType.objects.count() == 0
    assert Resource.objects.count() == 0

    call_command("initialize_resource_registry")

    registry = get_registry()
    expected_type_count = len(registry.get_resources())
    assert ResourceType.objects.count() == expected_type_count
    assert Resource.objects.count() > 0

    created_type_names = set(ResourceType.objects.values_list("name", flat=True))
    assert len(created_type_names) == expected_type_count


@pytest.mark.django_db
def test_initialize_resource_registry_is_idempotent(user):
    """Running the command twice produces the same result with identical records."""
    call_command("initialize_resource_registry")
    type_pks_1 = set(ResourceType.objects.values_list("pk", flat=True))
    resource_pks_1 = set(Resource.objects.values_list("pk", flat=True))

    call_command("initialize_resource_registry")
    type_pks_2 = set(ResourceType.objects.values_list("pk", flat=True))
    resource_pks_2 = set(Resource.objects.values_list("pk", flat=True))

    assert type_pks_1 == type_pks_2
    assert resource_pks_1 == resource_pks_2


@pytest.mark.django_db
def test_initialize_resource_registry_bypasses_migration_check(user):
    """Command still populates registry even when migrations_are_complete() returns False."""
    ResourceType.objects.all().delete()
    Resource.objects.all().delete()

    with mock.patch(
        "ansible_base.resource_registry.apps.migrations_are_complete",
        return_value=False,
    ):
        call_command("initialize_resource_registry")

    assert ResourceType.objects.count() > 0
    assert Resource.objects.count() > 0


@pytest.mark.django_db
def test_sync_recovers_wrong_content_type_with_stale_rows(user):
    """IntegrityError recovery corrects a mismatched content_type and removes stale rows."""
    from django.contrib.contenttypes.models import ContentType

    from ansible_base.authentication.models import Authenticator

    registry = get_registry()
    auth_ct = ContentType.objects.get_for_model(Authenticator)
    expected_name = f"{registry.api_config.service_type}.{auth_ct.model}"

    # Use a content_type that is not part of the resource registry.
    unrelated_ct = ContentType.objects.get_for_model(ContentType)

    ResourceType.objects.all().delete()
    Resource.objects.all().delete()

    # Simulate a bad migration: correct name but wrong content_type.
    wrong_rt = ResourceType.objects.create(
        name=expected_name,
        content_type=unrelated_ct,
        externally_managed=False,
    )
    # Stale row that already owns the correct content_type.
    stale_rt = ResourceType.objects.create(
        name="stale_placeholder",
        content_type=auth_ct,
        externally_managed=False,
    )

    call_command("initialize_resource_registry")

    wrong_rt.refresh_from_db()
    assert wrong_rt.content_type == auth_ct

    assert not ResourceType.objects.filter(pk=stale_rt.pk).exists()


@pytest.mark.django_db
def test_sync_reraises_unexpected_integrity_error():
    """An IntegrityError is re-raised when no ResourceType with the expected name exists."""
    from django.contrib.contenttypes.models import ContentType
    from django.db.utils import IntegrityError

    from ansible_base.resource_registry.apps import _sync_resource_types

    registry = get_registry()
    ResourceType.objects.all().delete()

    with mock.patch.object(
        ResourceType.objects,
        "update_or_create",
        side_effect=IntegrityError("simulated"),
    ):
        with pytest.raises(IntegrityError, match="simulated"):
            _sync_resource_types(registry, ResourceType, ContentType)
