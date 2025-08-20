from pathlib import Path
from unittest import mock
from uuid import uuid4

import pytest
from django.db.utils import Error

from ansible_base.lib.testing.util import StaticResourceAPIClient
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition
from ansible_base.resource_registry.models import Resource, ResourceType
from ansible_base.resource_registry.models.service_identifier import service_id
from ansible_base.resource_registry.tasks.sync import AssignmentTuple, ManifestItem, ResourceSyncHTTPError, SyncExecutor, _attempt_create_resource


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


@pytest.fixture()
def resource_to_delete(admin_api_client):
    # Create a local user that is managed by resource_server but not returned from the manifest

    url = get_relative_url("resource-list")
    resource = {
        "service_id": "57592fbc-7ecb-405f-9f5f-ebad20932d38",  # from fixtures/static/metadata
        "resource_type": "shared.user",
        "resource_data": {"username": "Phi", "last_name": "Lips", "email": "phi@example.com"},
    }
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201


@pytest.fixture()
def resource_to_update(admin_api_client):
    # Create a local user with different resource_data than the one manifest returns
    url = get_relative_url("resource-list")
    resource = {
        "resource_type": "shared.user",
        "service_id": "57592fbc-7ecb-405f-9f5f-ebad20932d38",  # from fixtures/static/metadata
        "ansible_id": "97447387-8596-404f-b0d0-6429b04c8d22",  # from fixtures/status/resources/{id}
        "resource_data": {
            "username": "theceo",
            "email": "theceo@other-email.com",
            "first_name": "A Different",
            "last_name": "Other Name",
        },
    }
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201


@pytest.fixture
def stdout():
    class Stdout:
        def __init__(self):
            self.lines = []

        def write(self, text):
            self.lines.append(text)

    return Stdout()


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
    assert 'CREATED 97447387-8596-404f-b0d0-6429b04c8d22 theceo' in stdout.lines


@pytest.mark.django_db
def test_delete_orphans(static_api_client, stdout, resource_to_delete):

    print(Resource.objects.filter(content_type__resource_type__name="shared.user").values_list("name"))

    # The previously created user must now be deleted
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
    executor.run()

    print(Resource.objects.filter(content_type__resource_type__name="shared.user").values_list("name"))

    print(stdout.lines)
    assert 'Deleting 1 orphaned resources' in stdout.lines
    assert any('Deleted 1' in line for line in stdout.lines)


@pytest.mark.django_db
def test_update_existing_resource(resource_to_update, static_api_client, stdout):
    # The previously created user must now be updated
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
    executor.run()
    assert 'UPDATED 97447387-8596-404f-b0d0-6429b04c8d22 theceo' in stdout.lines
    assert any('Updated 1' in line for line in stdout.lines)


@pytest.mark.django_db
def test_noop_existing_resource(admin_api_client, static_api_client, stdout):
    # Create a local user with EXACT resource_data of the one manifest returns
    url = get_relative_url("resource-list")
    resource = {
        "resource_type": "shared.user",
        "service_id": "57592fbc-7ecb-405f-9f5f-ebad20932d38",  # from fixtures/static/metadata
        "ansible_id": "97447387-8596-404f-b0d0-6429b04c8d22",  # from fixtures/status/resources/{id}
        "resource_data": {"username": "theceo", "email": "theceo@seriouscompany.com", "first_name": "The", "last_name": "CEO"},
    }
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201

    # The previously created user must be skipped
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
    executor.run()
    assert len(executor.results["noop"]) == 1
    assert 'NOOP 97447387-8596-404f-b0d0-6429b04c8d22' in stdout.lines
    assert any('Skipped 1' in line for line in stdout.lines)


@pytest.mark.django_db
def test_resource_sync_update_conflict(static_api_client, stdout, resource_to_update, admin_api_client):
    # Update the ansible ID on the local resources so that it causes a conflict to happen.
    resource = Resource.objects.get(ansible_id="97447387-8596-404f-b0d0-6429b04c8d22")
    resource.content_object.username = "different"
    resource.content_object.save()

    new_id = "b19ff84f-df6a-462a-ac81-167b1dc8f933"  # from fixtures/status/resources/{id}

    url = get_relative_url("resource-list")
    resource = {
        "resource_type": "shared.user",
        "service_id": str(service_id()),
        "ansible_id": new_id,
        "is_partially_migrated": False,
        "resource_data": {
            "username": "theceo",
            "email": "theceo@other-email.com",
            "first_name": "A Different",
            "last_name": "Other Name",
        },
    }
    response = admin_api_client.post(url, resource, format="json")
    assert response.status_code == 201

    assert Resource.objects.get(ansible_id=new_id).name == "theceo"

    executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
    executor.run()

    assert executor.deleted_count == 0
    assert len(stdout.lines) > 0
    assert 'UPDATED 97447387-8596-404f-b0d0-6429b04c8d22 theceo' in stdout.lines
    assert any('Updated 1' in line for line in stdout.lines)

    assert Resource.objects.get(ansible_id=new_id).name == "was_renamed"


@pytest.mark.django_db
def test_resource_sync_create_local_role_definition(static_api_client, stdout, resource_to_update):
    item_data = {"name": "Organization Inventory Role", "content_type": "shared.organization", "managed": True, "permissions": []}
    manifest_item = ManifestItem(str(uuid4()), str(uuid4()), item_data)
    result = _attempt_create_resource(
        manifest_item=manifest_item,
        resource_data=item_data,
        resource_type=ResourceType.objects.get(name='shared.roledefinition'),
        resource_service_id=str(uuid4()),
        api_client=static_api_client,  # unused
    )
    assert result.status == 'created'


@pytest.mark.django_db
def test_resource_sync_create_non_local_role_definition(static_api_client, stdout, resource_to_update):
    item_data = {"name": "Remote Role", "content_type": "shared.foo_type", "managed": True, "permissions": []}
    manifest_item = ManifestItem(str(uuid4()), str(uuid4()), item_data)
    result = _attempt_create_resource(
        manifest_item=manifest_item,
        resource_data=item_data,
        resource_type=ResourceType.objects.get(name='shared.roledefinition'),
        resource_service_id=str(uuid4()),
        api_client=static_api_client,  # unused
    )
    assert result.status == 'noop'

    assert not RoleDefinition.objects.filter(name="Remote Role").exists()


@pytest.mark.django_db
def test_resource_sync_create_conflict(static_api_client, stdout, resource_to_update):
    # Update the ansible ID on the local resources so that it causes a conflict to happen.
    resource = Resource.objects.get(ansible_id="97447387-8596-404f-b0d0-6429b04c8d22")
    new_id = str(uuid4())
    resource.ansible_id = new_id
    resource.service_id = service_id()
    resource.is_partially_migrated = False
    resource.save()

    assert Resource.objects.filter(ansible_id=new_id).exists()

    executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
    executor.run()

    assert executor.deleted_count == 0
    assert len(stdout.lines) > 0
    assert 'CREATED 3e3cc6a4-72fa-43ec-9e17-76ae5a3846ca Serious Company' in stdout.lines
    assert 'CREATED 97447387-8596-404f-b0d0-6429b04c8d22 theceo' in stdout.lines

    assert not Resource.objects.filter(ansible_id=new_id).exists()


@pytest.mark.django_db
def test_sync_error_handling_update(resource_to_update, static_api_client, stdout):
    with mock.patch("ansible_base.resource_registry.models.resource.Resource.update_resource", side_effect=Error("Something went wrong")):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor.run()
        any('Errors 1' in line for line in stdout.lines)


@pytest.mark.django_db
def test_sync_error_handling_delete(resource_to_delete, static_api_client, stdout):
    with mock.patch("ansible_base.resource_registry.models.resource.Resource.delete_resource", side_effect=Error("Something went wrong")):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor.run()
        any('Errors 1' in line for line in stdout.lines)


@pytest.mark.django_db
def test_sync_error_handling_create(static_api_client, stdout):
    with mock.patch("ansible_base.resource_registry.models.resource.Resource.create_resource", side_effect=Error("Something went wrong")):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor.run()
        any('Errors 1' in line for line in stdout.lines)


@mock.patch('ansible_base.resource_registry.tasks.sync.create_local_assignment')
@mock.patch('ansible_base.resource_registry.tasks.sync.delete_local_assignment')
@pytest.mark.django_db
def test_role_assignment_resource_sync(mock_delete, mock_create, static_api_client, stdout):
    mock_delete.return_value = True
    mock_create.return_value = True

    # Mock a remote assignment that does not exist locally to test creation
    with mock.patch(
        "ansible_base.resource_registry.tasks.sync.get_remote_assignments",
        return_value={
            AssignmentTuple(
                actor_ansible_id='97447387-8596-404f-b0d0-6429b04c8d22', ansible_id_or_pk='1', role_definition_name='Team Member', assignment_type='user'
            ),
        },
    ):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor._sync_assignments()

        assert '>>> Syncing role assignments' in stdout.lines
        assert executor.results["assignments_created"] == [1]
        assert executor.results["assignments_deleted"] == [0]
        assert executor.results["assignment_errors"] == [0]

    # Mock a local assignment with no matching remote assignment to test deletion
    with mock.patch(
        "ansible_base.resource_registry.tasks.sync.get_local_assignments",
        return_value={
            AssignmentTuple(
                actor_ansible_id='97447387-8596-404f-b0d0-6429b04c8d22', ansible_id_or_pk='1', role_definition_name='Team Member', assignment_type='user'
            ),
        },
    ):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor._sync_assignments()

        assert '>>> Syncing role assignments' in stdout.lines
        assert executor.results["assignments_created"] == [0]
        assert executor.results["assignments_deleted"] == [1]
        assert executor.results["assignment_errors"] == [0]
