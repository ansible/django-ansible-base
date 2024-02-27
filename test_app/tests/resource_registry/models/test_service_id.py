import pytest

from ansible_base.resource_registry.models.service_id import ServiceID


@pytest.mark.django_db
def test_service_id_already_exists():
    "The resource registry already creates this, so we expect an error here"
    with pytest.raises(RuntimeError) as exc:
        ServiceID.objects.create()
    assert 'This service already has a ServiceID' in str(exc)


@pytest.mark.django_db
def test_service_id_does_not_yet_exist():
    ServiceID.objects.first().delete()  # clear out what migration created
    ServiceID.objects.create()  # expect no error
