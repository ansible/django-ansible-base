from pathlib import Path

import pytest
from django.urls import reverse

from ansible_base.lib.testing.util import StaticResourceAPIClient
from ansible_base.resource_registry.tasks.sync import ResourceSyncHTTPError, SyncExecutor


@pytest.fixture(scope="function")
def static_api_client():
    """Responds raw response from test_app/tests/fixtures/static/resource_sync/"""
    current_file_path = Path(__file__).resolve()
    current_directory = current_file_path.parent
    service_url = current_directory.parent / "fixtures"
    service_path = "/static/resource_sync/"
    return StaticResourceAPIClient(
        service_url=str(service_url),
        service_path=str(service_path),
    )


@pytest.fixture
def stdout():
    class Stdout:
        def __init__(self):
            self.lines = []

        def write(self, text):
            self.lines.append(text)

    return Stdout()


def test_config_is_required():
    with pytest.raises(AttributeError) as exc:
        SyncExecutor()
    assert "'Settings' object has no attribute 'RESOURCE_JWT_USER_ID'" in str(exc)


def test_manifest_not_found(static_api_client, stdout):
    executor = SyncExecutor(api_client=static_api_client, resource_type_names=["shared.team"], stdout=stdout)
    executor.run()
    assert 'manifest for shared.team NOT FOUND.' in stdout.lines


def test_raises_manifest_stream_is_unavailable(static_api_client, stdout):
    static_api_client.router["resource-types/shared.organization/manifest/"] = {"status_code": 500, "content": "Server Error"}
    with pytest.raises(ResourceSyncHTTPError):
        executor = SyncExecutor(api_client=static_api_client, resource_type_names=["shared.organization"], stdout=stdout)
        executor.run()


@pytest.mark.django_db
def test_resource_sync(static_api_client, stdout):
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
    executor.run()

    assert executor.deleted_count == 0
    assert len(stdout.lines) > 0
    assert 'CREATED 3e3cc6a4-72fa-43ec-9e17-76ae5a3846ca Serious Company' in stdout.lines
    assert 'CONFLICT 31daab14-cb67-4c62-8dcd-39f411c82242 _system' in stdout.lines
    assert 'CREATED 97447387-8596-404f-b0d0-6429b04c8d22 theceo' in stdout.lines


@pytest.mark.django_db
def test_delete_orphans(admin_api_client, static_api_client, stdout):

    # Create a local user that is managed by resource_server but not returned from the manifest
    url = reverse("resource-list")
    resource = {
        "service_id": "57592fbc-7ecb-405f-9f5f-ebad20932d38",  # from fixtures/static/metadata
        "resource_type": "shared.user",
        "resource_data": {"username": "Phi", "last_name": "Lips", "email": "phi@example.com", "is_superuser": False},
    }
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201

    # The previously created user must now be deleted
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout, retain_seconds=0)
    executor.run()
    assert 'Deleting 1 orphaned resources' in stdout.lines
    assert any('Deleted 1' in line for line in stdout.lines)


@pytest.mark.django_db
def test_update_existing_resource(admin_api_client, static_api_client, stdout):

    # Create a local user with different resource_data than the one manifest returns
    url = reverse("resource-list")
    resource = {
        "resource_type": "shared.user",
        "service_id": "57592fbc-7ecb-405f-9f5f-ebad20932d38",  # from fixtures/static/metadata
        "ansible_id": "97447387-8596-404f-b0d0-6429b04c8d22",  # from fixtures/status/resources/{id}
        "resource_data": {
            "username": "theceo",
            "email": "theceo@other-email.com",
            "first_name": "A Different",
            "last_name": "Other Name",
            "is_superuser": True,
        },
    }
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201

    # The previously created user must now be updated
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout, retain_seconds=0)
    executor.run()
    assert 'UPDATED 97447387-8596-404f-b0d0-6429b04c8d22 theceo' in stdout.lines
    assert any('Updated 1' in line for line in stdout.lines)


@pytest.mark.django_db
def test_noop_existing_resource(admin_api_client, static_api_client, stdout):

    # Create a local user with EXACT resource_data of the one manifest returns
    url = reverse("resource-list")
    resource = {
        "resource_type": "shared.user",
        "service_id": "57592fbc-7ecb-405f-9f5f-ebad20932d38",  # from fixtures/static/metadata
        "ansible_id": "97447387-8596-404f-b0d0-6429b04c8d22",  # from fixtures/status/resources/{id}
        "resource_data": {"username": "theceo", "email": "theceo@seriouscompany.com", "first_name": "The", "last_name": "CEO", "is_superuser": True},
    }
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201

    # The previously created user must be skipped
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout, retain_seconds=0)
    executor.run()
    assert 'NOOP 97447387-8596-404f-b0d0-6429b04c8d22' in stdout.lines
    assert any('Skipped 1' in line for line in stdout.lines)
