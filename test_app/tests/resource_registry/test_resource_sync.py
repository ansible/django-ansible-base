from pathlib import Path
from unittest import mock
from uuid import uuid4

import pytest
from django.db.utils import Error
from django.test import override_settings

from ansible_base.lib.testing.util import StaticResourceAPIClient
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition
from ansible_base.resource_registry.models import Resource, ResourceType
from ansible_base.resource_registry.models.service_identifier import service_id
from ansible_base.resource_registry.tasks.sync import (
    DEFAULT_SYNC_JWT_EXPIRATION,
    DEFAULT_SYNC_PAGE_SIZE,
    AssignmentTuple,
    ManifestItem,
    RemoteAssignmentFetcher,
    RemoteAssignmentResult,
    ResourceSyncHTTPError,
    SyncExecutor,
    _attempt_create_resource,
    _attempt_update_resource,
    create_api_client,
    get_remote_assignments,
)


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


@pytest.mark.django_db
def test_manifest_not_found(static_api_client, stdout):
    executor = SyncExecutor(api_client=static_api_client, resource_type_names=["shared.team"], stdout=stdout)
    executor.run()
    assert 'manifest for shared.team NOT FOUND.' in stdout.lines


@pytest.mark.django_db
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


@pytest.mark.parametrize(
    "name,expected_status",
    [
        ("Platform Auditor", "noop"),  # Same name as existing resource, should skip
        ("Platform Auditor DIFFERENCE", "updated"),  # Different name, should update
    ],
)
@pytest.mark.django_db
def test_resource_sync_update_scenarios(static_api_client, resource_to_update, name, expected_status):
    """Test resource sync update scenarios with different names."""
    # Get the existing resource that was created by the fixture
    resource = Resource.objects.get(ansible_id="97447387-8596-404f-b0d0-6429b04c8d22")
    auditor_rd = RoleDefinition.objects.managed.sys_auditor
    resource = auditor_rd.resource

    # Create manifest item and resource data with invalid content_type
    item_data = {
        'name': name,
        'description': 'Has view permissions to all objects',
        'managed': True,
        'content_type': None,
        'permissions': [
            'eda.view_activation',
            'galaxy.view_ansiblerepository',
            'eda.view_auditrule',
            'galaxy.view_collection',
            'galaxy.view_collectionimport',
            'galaxy.view_collectionremote',
            'galaxy.view_containernamespace',
            'galaxy.view_containerregistryremote',
            'galaxy.view_containerrepository',
            'awx.view_credential',
            'eda.view_credentialinputsource',
            'eda.view_decisionenvironment',
            'eda.view_edacredential',
            'eda.view_eventstream',
            'awx.view_instancegroup',
            'awx.view_inventory',
            'shared.view_organization',
            'awx.view_jobtemplate',
            'galaxy.view_namespace',
            'awx.view_notificationtemplate',
            'awx.view_project',
            'eda.view_project',
            'eda.view_rulebook',
            'eda.view_rulebookprocess',
            'galaxy.view_task',
            'shared.view_team',
            'awx.view_workflowjobtemplate',
        ],
    }
    item_data['permissions'] += [perm.api_slug for perm in auditor_rd.permissions.all()]
    manifest_item = ManifestItem("97447387-8596-404f-b0d0-6429b04c8d22", str(uuid4()), item_data)

    # Test the update behavior
    result = _attempt_update_resource(
        manifest_item=manifest_item,
        resource=resource,
        resource_data=item_data,
        api_client=static_api_client,
    )

    assert result.status == expected_status


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
        return_value=RemoteAssignmentResult(
            assignments={
                AssignmentTuple(
                    actor_ansible_id='97447387-8596-404f-b0d0-6429b04c8d22', ansible_id_or_pk='1', role_definition_name='Team Member', assignment_type='user'
                ),
            },
            is_complete=True,
        ),
    ):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor._sync_assignments()

        assert '>>> Syncing role assignments' in stdout.lines
        assert executor.results["assignments_created"] == [1]
        assert executor.results["assignments_deleted"] == [0]
        assert executor.results["assignment_errors"] == [0]

    # Mock a local assignment with no matching remote assignment to test deletion
    with (
        mock.patch(
            "ansible_base.resource_registry.tasks.sync.get_remote_assignments",
            return_value=RemoteAssignmentResult(assignments=set(), is_complete=True),
        ),
        mock.patch(
            "ansible_base.resource_registry.tasks.sync.get_local_assignments",
            return_value={
                AssignmentTuple(
                    actor_ansible_id='97447387-8596-404f-b0d0-6429b04c8d22', ansible_id_or_pk='1', role_definition_name='Team Member', assignment_type='user'
                ),
            },
        ),
    ):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor._sync_assignments()

        assert '>>> Syncing role assignments' in stdout.lines
        assert executor.results["assignments_created"] == [0]
        assert executor.results["assignments_deleted"] == [1]
        assert executor.results["assignment_errors"] == [0]


@mock.patch('ansible_base.resource_registry.tasks.sync.create_local_assignment')
@mock.patch('ansible_base.resource_registry.tasks.sync.delete_local_assignment')
@pytest.mark.django_db
def test_role_assignment_sync_skips_deletions_on_incomplete_fetch(mock_delete, mock_create, static_api_client, stdout):
    """When the remote fetch is incomplete (e.g. HTTP error mid-pagination),
    deletions must be skipped to avoid removing valid local assignments
    that simply weren't fetched.  Creations from the partial set are still
    safe and should proceed."""
    mock_delete.return_value = True
    mock_create.return_value = True

    local_only = AssignmentTuple(
        actor_ansible_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        ansible_id_or_pk='1',
        role_definition_name='Team Admin',
        assignment_type='user',
    )
    remote_only = AssignmentTuple(
        actor_ansible_id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        ansible_id_or_pk='2',
        role_definition_name='Team Member',
        assignment_type='user',
    )

    with (
        mock.patch(
            "ansible_base.resource_registry.tasks.sync.get_remote_assignments",
            return_value=RemoteAssignmentResult(
                assignments={remote_only},
                is_complete=False,
            ),
        ),
        mock.patch(
            "ansible_base.resource_registry.tasks.sync.get_local_assignments",
            return_value={local_only},
        ),
    ):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor._sync_assignments()

        # Deletions must NOT happen — the remote set is partial
        mock_delete.assert_not_called()
        assert executor.results["assignments_deleted"] == [0]

        # Creations from the partial set are safe and should proceed
        mock_create.assert_called_once_with(remote_only)
        assert executor.results["assignments_created"] == [1]

        # Verify the skip message was logged
        assert any('Skipping assignment deletions' in line for line in stdout.lines)


def _mock_response(status_code=200, body=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.json.return_value = body or {"results": [], "next": None}
    return resp


@pytest.mark.django_db
@pytest.mark.parametrize("failure_mode", ["http_error", "exception"])
def test_get_remote_assignments_incomplete_on_failure(failure_mode):
    """is_complete must be False on HTTP error or exception mid-pagination."""
    RoleDefinition.objects.managed.team_member  # ensure the role exists for filtering
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    page1 = _mock_response(
        body={
            "results": [{"user_ansible_id": "u1", "object_ansible_id": "o1", "role_definition": "Team Member"}],
            "next": "http://example.com/page2",
        }
    )

    if failure_mode == "http_error":
        api_client.list_user_assignments.side_effect = [page1, _mock_response(status_code=500)]
    else:
        api_client.list_user_assignments.side_effect = [page1, ConnectionError("reset")]

    result = get_remote_assignments(api_client)

    assert result.is_complete is False
    # Compare fields directly — AssignmentTuple.__eq__ uses isinstance,
    # which can fail across pytest-xdist worker forks.
    assert len(result.assignments) == 1
    assignment = next(iter(result.assignments))
    assert assignment.actor_ansible_id == "u1"
    assert assignment.ansible_id_or_pk == "o1"
    assert assignment.role_definition_name == "Team Member"
    assert assignment.assignment_type == "user"

    # Team pagination must be skipped when user pagination fails
    api_client.list_team_assignments.assert_not_called()


@pytest.mark.django_db
def test_get_remote_assignments_complete_on_success():
    """is_complete must be True only when both pagination loops finish cleanly."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    ok = _mock_response()
    api_client.list_user_assignments.return_value = ok
    api_client.list_team_assignments.return_value = ok

    result = get_remote_assignments(api_client)

    assert result.is_complete is True
    assert len(result.assignments) == 0


@pytest.mark.django_db
def test_get_remote_assignments_filters_unknown_roles(static_api_client):
    """Assignments for roles that do not exist locally should be filtered out.

    The resource server returns assignments across all services. Roles from
    other services (e.g. Controller's 'Credential Admin') do not exist in the
    local database and must be skipped to avoid DoesNotExist errors.
    """
    local_role = RoleDefinition.objects.managed.sys_auditor

    user_results = {
        'results': [
            # Assignment for a role that exists locally — should be included
            {
                'user_ansible_id': 'aaaaaaaa-1111-2222-3333-444444444444',
                'object_ansible_id': '1',
                'role_definition': local_role.name,
            },
            # Assignment for a role from another service — should be filtered out
            {
                'user_ansible_id': 'bbbbbbbb-1111-2222-3333-444444444444',
                'object_ansible_id': '1',
                'role_definition': 'Credential Admin',
            },
        ],
        'next': None,
    }
    team_results = {
        'results': [
            # Assignment for a role from another service — should be filtered out
            {
                'team_ansible_id': 'cccccccc-1111-2222-3333-444444444444',
                'object_ansible_id': '1',
                'role_definition': 'Some Other Service Role',
            },
        ],
        'next': None,
    }

    user_response = mock.Mock(status_code=200)
    user_response.json.return_value = user_results
    team_response = mock.Mock(status_code=200)
    team_response.json.return_value = team_results

    static_api_client.list_user_assignments = mock.Mock(return_value=user_response)
    static_api_client.list_team_assignments = mock.Mock(return_value=team_response)

    result = get_remote_assignments(static_api_client)

    assert result.is_complete is True
    assert len(result.assignments) == 1
    assignment = next(iter(result.assignments))
    assert assignment.role_definition_name == local_role.name


@pytest.mark.django_db
def test_remote_assignment_fetcher_passes_page_size():
    """page_size should be included in the pagination filters."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    ok = _mock_response()
    api_client.list_user_assignments.return_value = ok
    api_client.list_team_assignments.return_value = ok

    RemoteAssignmentFetcher(api_client, page_size=100).fetch()

    api_client.list_user_assignments.assert_called_with(filters={'page': 1, 'page_size': 100})
    api_client.list_team_assignments.assert_called_with(filters={'page': 1, 'page_size': 100})


@pytest.mark.django_db
def test_remote_assignment_fetcher_reads_page_size_from_settings():
    """When page_size is not provided, it should be read from settings."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    ok = _mock_response()
    api_client.list_user_assignments.return_value = ok
    api_client.list_team_assignments.return_value = ok

    with override_settings(RESOURCE_SYNC_PAGE_SIZE=200):
        fetcher = RemoteAssignmentFetcher(api_client)
        assert fetcher.page_size == 200
        fetcher.fetch()

    api_client.list_user_assignments.assert_called_with(filters={'page': 1, 'page_size': 200})


@mock.patch('ansible_base.resource_registry.tasks.sync.get_remote_assignments')
@mock.patch('ansible_base.resource_registry.tasks.sync.get_local_assignments', return_value=set())
@pytest.mark.django_db
def test_sync_executor_passes_page_size(mock_local, mock_remote, static_api_client, stdout):
    """SyncExecutor should forward page_size to get_remote_assignments."""
    mock_remote.return_value = RemoteAssignmentResult(assignments=set(), is_complete=True)
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout, page_size=75)
    executor._sync_assignments()
    mock_remote.assert_called_once_with(static_api_client, page_size=75)


@mock.patch("ansible_base.resource_registry.tasks.sync.get_resource_server_client")
def test_create_api_client_reads_jwt_expiration(mock_get_client):
    """create_api_client should read RESOURCE_SYNC_JWT_EXPIRATION from settings."""
    mock_get_client.return_value = mock.Mock()

    with override_settings(
        RESOURCE_SERVICE_PATH="/api/gateway/v1/service-index/",
        RESOURCE_SYNC_JWT_EXPIRATION=120,
    ):
        create_api_client()

    assert mock_get_client.call_args.kwargs["jwt_expiration"] == 120


@pytest.mark.django_db
def test_remote_assignment_fetcher_default_page_size():
    """When no setting is configured, page_size should fall back to DEFAULT_SYNC_PAGE_SIZE."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    fetcher = RemoteAssignmentFetcher(api_client)
    assert fetcher.page_size == DEFAULT_SYNC_PAGE_SIZE


@mock.patch("ansible_base.resource_registry.tasks.sync.get_resource_server_client")
def test_create_api_client_default_jwt_expiration(mock_get_client):
    """When no setting is configured, jwt_expiration should fall back to DEFAULT_SYNC_JWT_EXPIRATION."""
    mock_get_client.return_value = mock.Mock()

    with override_settings(RESOURCE_SERVICE_PATH="/api/gateway/v1/service-index/"):
        create_api_client()

    assert mock_get_client.call_args.kwargs["jwt_expiration"] == DEFAULT_SYNC_JWT_EXPIRATION


@pytest.mark.django_db
def test_remote_assignment_fetcher_sends_page_size_on_all_pages():
    """page_size should be included in filters on every page, not just the first."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])

    page1 = _mock_response(body={"results": [], "next": "http://example.com/page2"})
    page2 = _mock_response(body={"results": [], "next": None})
    api_client.list_user_assignments.side_effect = [page1, page2]
    api_client.list_team_assignments.return_value = _mock_response()

    RemoteAssignmentFetcher(api_client, page_size=100).fetch()

    user_calls = api_client.list_user_assignments.call_args_list
    assert len(user_calls) == 2
    assert user_calls[0] == mock.call(filters={'page': 1, 'page_size': 100})
    assert user_calls[1] == mock.call(filters={'page': 2, 'page_size': 100})
