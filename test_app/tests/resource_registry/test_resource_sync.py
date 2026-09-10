from pathlib import Path
from unittest import mock
from uuid import uuid4

import pytest
from django.db.utils import Error, IntegrityError
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
from test_app.models import User


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
def test_remote_assignment_fetcher_passes_service_filter_in_pagination():
    """service_filter should be included as content_type__service in pagination filters."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    ok = _mock_response()
    api_client.list_user_assignments.return_value = ok
    api_client.list_team_assignments.return_value = ok

    RemoteAssignmentFetcher(api_client, page_size=100, service_filter='controller').fetch()

    expected_filters = {'page': 1, 'page_size': 100, 'content_type__service': 'controller'}
    api_client.list_user_assignments.assert_called_with(filters=expected_filters)
    api_client.list_team_assignments.assert_called_with(filters=expected_filters)


@pytest.mark.django_db
def test_remote_assignment_fetcher_omits_service_filter_when_none():
    """When service_filter is None, content_type__service should not be in filters."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    ok = _mock_response()
    api_client.list_user_assignments.return_value = ok
    api_client.list_team_assignments.return_value = ok

    RemoteAssignmentFetcher(api_client, page_size=100, service_filter=None).fetch()

    api_client.list_user_assignments.assert_called_with(filters={'page': 1, 'page_size': 100})
    assert 'content_type__service' not in api_client.list_user_assignments.call_args.kwargs.get(
        'filters', api_client.list_user_assignments.call_args[1].get('filters', {})
    )


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
    mock_remote.assert_called_once_with(static_api_client, page_size=75, service_filter=None)


@mock.patch('ansible_base.resource_registry.tasks.sync.get_remote_assignments')
@mock.patch('ansible_base.resource_registry.tasks.sync.get_local_assignments', return_value=set())
@pytest.mark.django_db
def test_sync_executor_passes_service_filter(mock_local, mock_remote, static_api_client, stdout):
    """SyncExecutor should forward service_filter to get_remote_assignments and get_local_assignments."""
    mock_remote.return_value = RemoteAssignmentResult(assignments=set(), is_complete=True)
    executor = SyncExecutor(api_client=static_api_client, stdout=stdout, service_filter='controller')
    executor._sync_assignments()
    mock_remote.assert_called_once_with(static_api_client, page_size=None, service_filter='controller')
    mock_local.assert_called_once_with(service='controller')


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


@pytest.mark.django_db
def test_get_remote_assignments_handles_null_results():
    """Regression test for AAP-74082: API returning {"results": null} should not crash.

    When the RBAC query returns no matching role assignments (after the optimization
    in commit 28d9875), the API may return {"results": null} instead of {"results": []}.
    The code must handle null values gracefully without raising TypeError.
    """
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])

    # Mock API responses with null results (reproduces the bug condition)
    null_response = _mock_response(body={"results": None, "next": None})
    api_client.list_user_assignments.return_value = null_response
    api_client.list_team_assignments.return_value = null_response

    result = get_remote_assignments(api_client)

    # Should complete successfully without TypeError
    assert result.is_complete is True
    assert len(result.assignments) == 0


@pytest.mark.django_db
def test_remote_assignment_fetcher_multi_page_with_assignments():
    """Multi-page pagination collects assignments across pages and increments page number."""
    from ansible_base.rbac.models import RoleDefinition

    RoleDefinition.objects.create(name='MultiPageRole', managed=True)

    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    page1 = _mock_response(
        body={
            'results': [
                {'user_ansible_id': 'u1', 'object_ansible_id': 'obj1', 'role_definition': 'MultiPageRole'},
            ],
            'next': 'http://example.com/page2',
        }
    )
    page2 = _mock_response(
        body={
            'results': [
                {'user_ansible_id': 'u2', 'object_ansible_id': 'obj2', 'role_definition': 'MultiPageRole'},
            ],
            'next': None,
        }
    )
    api_client.list_user_assignments.side_effect = [page1, page2]
    api_client.list_team_assignments.return_value = _mock_response()

    result = RemoteAssignmentFetcher(api_client, page_size=1).fetch()

    assert result.is_complete is True
    assert len(result.assignments) == 2
    user_calls = api_client.list_user_assignments.call_args_list
    assert len(user_calls) == 2
    assert user_calls[0] == mock.call(filters={'page': 1, 'page_size': 1})
    assert user_calls[1] == mock.call(filters={'page': 2, 'page_size': 1})


@pytest.mark.django_db
def test_remote_assignment_fetcher_http_error_returns_incomplete():
    """Non-200 status code marks result as incomplete with warning."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    api_client.list_user_assignments.return_value = _mock_response(status_code=500)

    result = RemoteAssignmentFetcher(api_client).fetch()

    assert result.is_complete is False
    assert len(result.assignments) == 0


@pytest.mark.django_db
def test_remote_assignment_fetcher_handles_connection_error():
    """_paginate exception path: a network error marks the result as incomplete."""
    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    api_client.list_user_assignments.side_effect = ConnectionError("timeout")

    result = RemoteAssignmentFetcher(api_client).fetch()

    assert result.is_complete is False
    assert len(result.assignments) == 0


@pytest.mark.django_db
def test_remote_assignment_fetcher_uses_object_id_fallback():
    """When object_ansible_id is absent, object_id is used instead."""
    from ansible_base.rbac.models import RoleDefinition

    RoleDefinition.objects.create(name='FallbackRole', managed=True)

    api_client = mock.Mock(spec=["list_user_assignments", "list_team_assignments"])
    api_client.list_user_assignments.return_value = _mock_response(
        body={
            'results': [
                {'user_ansible_id': 'u1', 'role_definition': 'FallbackRole', 'object_id': '42'},
            ],
            'next': None,
        }
    )
    api_client.list_team_assignments.return_value = _mock_response()

    result = RemoteAssignmentFetcher(api_client).fetch()

    assert result.is_complete is True
    assert len(result.assignments) == 1
    assignment = next(iter(result.assignments))
    assert assignment.ansible_id_or_pk == '42'


@pytest.mark.django_db
def test_delete_local_assignment_exception_handling(static_api_client, stdout):
    """Test that delete_local_assignment logs exceptions with logger.exception."""
    from ansible_base.resource_registry.tasks.sync import delete_local_assignment

    # Create an assignment tuple that will cause an exception
    assignment_tuple = AssignmentTuple(
        actor_ansible_id='nonexistent-user-id',
        ansible_id_or_pk='1',
        role_definition_name='Team Member',
        assignment_type='user',
    )

    # Should return False and log the exception
    result = delete_local_assignment(assignment_tuple)
    assert result is False


@pytest.mark.django_db
def test_create_local_assignment_exception_handling(static_api_client, stdout):
    """Test that create_local_assignment logs exceptions with logger.exception."""
    from ansible_base.resource_registry.tasks.sync import create_local_assignment

    # Create an assignment tuple that will cause an exception
    assignment_tuple = AssignmentTuple(
        actor_ansible_id='nonexistent-user-id',
        ansible_id_or_pk='1',
        role_definition_name='Team Member',
        assignment_type='user',
    )

    # Should return False and log the exception
    result = create_local_assignment(assignment_tuple)
    assert result is False


@pytest.mark.django_db
def test_attempt_update_resource_conflict_exception(static_api_client, resource_to_update):
    """Test that _attempt_update_resource conflict handler logs exceptions with logger.exception."""
    from django.db.utils import IntegrityError

    resource = Resource.objects.get(ansible_id="97447387-8596-404f-b0d0-6429b04c8d22")
    manifest_item = ManifestItem("97447387-8596-404f-b0d0-6429b04c8d22", str(uuid4()), {})
    resource_data = {"username": "theceo", "email": "theceo@example.com"}

    # Mock update_resource to raise IntegrityError, then _handle_conflict to raise another error
    with (
        mock.patch.object(resource, 'update_resource', side_effect=IntegrityError("Duplicate key")),
        mock.patch('ansible_base.resource_registry.tasks.sync._handle_conflict', side_effect=Error("Conflict handling failed")),
    ):
        result = _attempt_update_resource(manifest_item, resource, resource_data, static_api_client)
        assert result.status == 'conflict'


@pytest.mark.django_db
def test_attempt_update_resource_error_exception(static_api_client, resource_to_update):
    """Test that _attempt_update_resource error handler logs exceptions with logger.exception."""
    resource = Resource.objects.get(ansible_id="97447387-8596-404f-b0d0-6429b04c8d22")
    manifest_item = ManifestItem("97447387-8596-404f-b0d0-6429b04c8d22", str(uuid4()), {})
    resource_data = {"username": "theceo", "email": "theceo@example.com"}

    # Mock update_resource to raise Error directly (not IntegrityError)
    with mock.patch.object(resource, 'update_resource', side_effect=Error("Database error")):
        result = _attempt_update_resource(manifest_item, resource, resource_data, static_api_client)
        assert result.status == 'error'


@pytest.mark.django_db
def test_delete_resource_exception_handling():
    """Test that delete_resource logs exceptions with logger.exception."""
    from ansible_base.resource_registry.tasks.sync import ResourceDeletionError, delete_resource

    # Create a user (which will auto-create a Resource via signals)
    user = User.objects.create(username='testuser', email='test@example.com')
    resource = Resource.get_resource_for_object(user)

    # Mock delete_resource to raise an Error
    with mock.patch.object(resource, 'delete_resource', side_effect=Error("Delete failed")):
        with pytest.raises(ResourceDeletionError):
            delete_resource(resource)


@override_settings(RESOURCE_JWT_USER_ID='test-user-id', RESOURCE_SERVICE_PATH='/api/v1/', RESOURCE_SYNC_JWT_EXPIRATION=120)
@mock.patch('ansible_base.resource_registry.tasks.sync.get_resource_server_client')
def test_create_api_client_with_jwt_user_id(mock_get_client):
    """Test create_api_client includes jwt_user_id when set in settings."""
    create_api_client()

    mock_get_client.assert_called_once_with(
        raise_if_bad_request=False,
        jwt_user_id='test-user-id',
        service_path='/api/v1/',
        jwt_expiration=120,
    )


@override_settings(RESOURCE_SERVICE_PATH='')
def test_create_api_client_missing_service_path():
    """Test create_api_client raises ValueError when RESOURCE_SERVICE_PATH is not set."""
    with pytest.raises(ValueError, match="RESOURCE_SERVICE_PATH is not set"):
        create_api_client()


@pytest.mark.django_db
def test_get_ansible_id_or_pk_for_organization():
    """Test get_ansible_id_or_pk returns ansible_id for organization assignments."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_ansible_id_or_pk
    from test_app.models import Organization, User

    # Create an organization with resource
    org = Organization.objects.create(name='Test Org')
    org_resource = Resource.get_resource_for_object(org)
    org_dab_ct = DABContentType.objects.get_for_model(Organization)

    # Create a role definition and assignment
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=org_dab_ct, managed=True)
    user = User.objects.create(username='testuser', email='test@example.com')
    assignment = role_def.give_permission(user, org)

    # Test get_ansible_id_or_pk
    result = get_ansible_id_or_pk(assignment)
    assert result == str(org_resource.ansible_id)


@pytest.mark.django_db
def test_get_ansible_id_or_pk_for_team():
    """Test get_ansible_id_or_pk returns ansible_id for team assignments."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_ansible_id_or_pk
    from test_app.models import Organization, Team, User

    # Create a team with resource
    org = Organization.objects.create(name='Test Org')
    team = Team.objects.create(name='Test Team', organization=org)
    team_resource = Resource.get_resource_for_object(team)
    team_dab_ct = DABContentType.objects.get_for_model(Team)

    # Create a role definition and assignment
    role_def = RoleDefinition.objects.create(name='Team Admin', content_type=team_dab_ct, managed=True)
    user = User.objects.create(username='testuser', email='test@example.com')
    assignment = role_def.give_permission(user, team)

    # Test get_ansible_id_or_pk
    result = get_ansible_id_or_pk(assignment)
    assert result == str(team_resource.ansible_id)


@pytest.mark.django_db
def test_get_ansible_id_or_pk_raises_for_missing_resource():
    """Test get_ansible_id_or_pk raises RuntimeError when organization has no Resource."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_ansible_id_or_pk
    from test_app.models import Organization, User

    # Create an organization
    org = Organization.objects.create(name='Test Org')
    org_resource = Resource.get_resource_for_object(org)
    org_dab_ct = DABContentType.objects.get_for_model(Organization)
    # Delete the resource to simulate missing resource
    org_resource.delete()

    # Create a role definition and assignment
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=org_dab_ct, managed=True)
    user = User.objects.create(username='testuser', email='test@example.com')
    assignment = role_def.give_permission(user, org)

    # Test get_ansible_id_or_pk raises
    with pytest.raises(RuntimeError, match="organization .* was found without an associated Resource"):
        get_ansible_id_or_pk(assignment)


@pytest.mark.django_db
def test_get_content_object_for_organization():
    """Test get_content_object retrieves organization by ansible_id."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_content_object
    from test_app.models import Organization

    # Create an organization
    org = Organization.objects.create(name='Test Org')
    org_resource = Resource.get_resource_for_object(org)

    # Create role definition
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=DABContentType.objects.get_for_model(Organization), managed=True)

    # Create assignment tuple
    assignment_tuple = AssignmentTuple(
        actor_ansible_id=str(uuid4()),
        ansible_id_or_pk=str(org_resource.ansible_id),
        role_definition_name='Org Admin',
        assignment_type='user',
    )

    result = get_content_object(role_def, assignment_tuple)
    assert result == org


@pytest.mark.django_db
def test_get_content_object_for_team():
    """Test get_content_object retrieves team by ansible_id."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_content_object
    from test_app.models import Organization, Team

    # Create a team
    org = Organization.objects.create(name='Test Org')
    team = Team.objects.create(name='Test Team', organization=org)
    team_resource = Resource.get_resource_for_object(team)

    # Create role definition
    role_def = RoleDefinition.objects.create(name='Team Admin', content_type=DABContentType.objects.get_for_model(Team), managed=True)

    # Create assignment tuple
    assignment_tuple = AssignmentTuple(
        actor_ansible_id=str(uuid4()),
        ansible_id_or_pk=str(team_resource.ansible_id),
        role_definition_name='Team Admin',
        assignment_type='user',
    )

    result = get_content_object(role_def, assignment_tuple)
    assert result == team


@pytest.mark.django_db
def test_get_local_assignments_skips_users_without_resources():
    """Test get_local_assignments skips user assignments when user has no Resource."""
    from ansible_base.rbac.models import RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_local_assignments

    # Create a user with resource
    user = User.objects.create(username='testuser', email='test@example.com')
    user_resource = Resource.get_resource_for_object(user)

    # Create a global role assignment
    role_def = RoleDefinition.objects.create(name='Global Admin', managed=True)
    role_def.give_global_permission(user)

    # Delete the user's resource to simulate missing resource
    user_resource.delete()

    # Get local assignments - should skip the user assignment
    assignments = get_local_assignments()
    assert len([a for a in assignments if a.assignment_type == 'user']) == 0


@pytest.mark.django_db
def test_get_local_assignments_skips_teams_without_resources():
    """Test get_local_assignments skips team assignments when team has no Resource."""
    from ansible_base.rbac.models import RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_local_assignments
    from test_app.models import Organization, Team

    # Create a team with resource
    org = Organization.objects.create(name='Test Org')
    team = Team.objects.create(name='Test Team', organization=org)
    team_resource = Resource.get_resource_for_object(team)

    # Create a global role assignment
    role_def = RoleDefinition.objects.create(name='Global Admin', managed=True)
    role_def.give_global_permission(team)

    # Delete the team's resource to simulate missing resource
    team_resource.delete()

    # Get local assignments - should skip the team assignment
    assignments = get_local_assignments()
    assert len([a for a in assignments if a.assignment_type == 'team']) == 0


@pytest.mark.django_db
def test_get_local_assignments_with_object_scoped_user_assignment():
    """Test get_local_assignments includes object-scoped user assignments."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_local_assignments
    from test_app.models import Organization, User

    # Create a user and organization
    user = User.objects.create(username='testuser', email='test@example.com')
    user_resource = Resource.get_resource_for_object(user)
    org = Organization.objects.create(name='Test Org')
    org_resource = Resource.get_resource_for_object(org)
    org_dab_ct = DABContentType.objects.get_for_model(Organization)

    # Create an object-scoped role assignment
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=org_dab_ct, managed=True)
    role_def.give_permission(user, org)

    # Get local assignments
    assignments = get_local_assignments()
    user_assignments = [a for a in assignments if a.assignment_type == 'user']

    assert len(user_assignments) == 1
    assert user_assignments[0].actor_ansible_id == str(user_resource.ansible_id)
    assert user_assignments[0].ansible_id_or_pk == str(org_resource.ansible_id)
    assert user_assignments[0].role_definition_name == 'Org Admin'


@pytest.mark.django_db
def test_get_local_assignments_with_object_scoped_team_assignment():
    """Test get_local_assignments includes object-scoped team assignments."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_local_assignments
    from test_app.models import Organization, Team

    # Create a team and organization
    org = Organization.objects.create(name='Test Org')
    team = Team.objects.create(name='Test Team', organization=org)
    team_resource = Resource.get_resource_for_object(team)
    target_org = Organization.objects.create(name='Target Org')
    target_org_resource = Resource.get_resource_for_object(target_org)
    target_org_dab_ct = DABContentType.objects.get_for_model(Organization)

    # Create an object-scoped role assignment
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=target_org_dab_ct, managed=True)
    role_def.give_permission(team, target_org)

    # Get local assignments
    assignments = get_local_assignments()
    team_assignments = [a for a in assignments if a.assignment_type == 'team']

    assert len(team_assignments) == 1
    assert team_assignments[0].actor_ansible_id == str(team_resource.ansible_id)
    assert team_assignments[0].ansible_id_or_pk == str(target_org_resource.ansible_id)
    assert team_assignments[0].role_definition_name == 'Org Admin'


def test_assignment_tuple_equality_with_non_tuple():
    """Test AssignmentTuple.__eq__ returns False for non-AssignmentTuple objects."""
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple

    tuple1 = AssignmentTuple(
        actor_ansible_id='user123',
        ansible_id_or_pk='obj456',
        role_definition_name='Admin',
        assignment_type='user',
    )

    # Test with non-AssignmentTuple objects
    assert tuple1 != "not an assignment tuple"
    assert tuple1 != 123
    assert tuple1 is not None
    assert tuple1 != {'actor_ansible_id': 'user123'}


def test_assignment_tuple_equality_comparison():
    """Test AssignmentTuple.__eq__ field comparison for equal and unequal tuples."""
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple

    tuple1 = AssignmentTuple(
        actor_ansible_id='user123',
        ansible_id_or_pk='obj456',
        role_definition_name='Admin',
        assignment_type='user',
    )
    tuple2 = AssignmentTuple(
        actor_ansible_id='user123',
        ansible_id_or_pk='obj456',
        role_definition_name='Admin',
        assignment_type='user',
    )
    tuple3 = AssignmentTuple(
        actor_ansible_id='user999',
        ansible_id_or_pk='obj456',
        role_definition_name='Admin',
        assignment_type='user',
    )

    # Test equality - should compare all fields
    assert tuple1 == tuple2
    # Test inequality - different actor_ansible_id
    assert tuple1 != tuple3


@pytest.mark.django_db
def test_get_ansible_id_or_pk_for_non_org_team():
    """Test get_ansible_id_or_pk returns object_id for non-org/team models."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import get_ansible_id_or_pk
    from test_app.models import Inventory, Organization

    # Create inventory (not org/team)
    org = Organization.objects.create(name='Test Org')
    inventory = Inventory.objects.create(name='Test Inventory', organization=org)
    inv_dab_ct = DABContentType.objects.get_for_model(Inventory)

    # Create role and assignment
    role_def = RoleDefinition.objects.create(name='Inventory Admin', content_type=inv_dab_ct, managed=True)

    user = User.objects.create(username='testuser', email='test@example.com')
    assignment = role_def.give_permission(user, inventory)

    # Should return object_id (pk) instead of ansible_id
    result = get_ansible_id_or_pk(assignment)
    assert result == str(inventory.pk)


@pytest.mark.django_db
def test_get_content_object_for_non_org_team():
    """Test get_content_object retrieves non-org/team objects by pk."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple, get_content_object
    from test_app.models import Inventory, Organization

    # Create inventory
    org = Organization.objects.create(name='Test Org')
    inventory = Inventory.objects.create(name='Test Inventory', organization=org)
    inv_dab_ct = DABContentType.objects.get_for_model(Inventory)

    # Create role definition
    role_def = RoleDefinition.objects.create(name='Inventory Admin', content_type=inv_dab_ct, managed=True)

    # Create assignment tuple with pk (not ansible_id)
    assignment_tuple = AssignmentTuple(
        actor_ansible_id='user123',
        ansible_id_or_pk=str(inventory.pk),
        role_definition_name='Inventory Admin',
        assignment_type='user',
    )

    result = get_content_object(role_def, assignment_tuple)
    assert result == inventory


@pytest.mark.django_db
@mock.patch('ansible_base.resource_registry.tasks.sync.RemoteAssignmentFetcher._paginate')
def test_get_remote_assignments_fails_on_user_pagination(mock_paginate):
    """Test get_remote_assignments returns incomplete when user pagination fails."""
    from ansible_base.resource_registry.tasks.sync import create_api_client, get_remote_assignments

    # Make user pagination fail
    mock_paginate.return_value = False

    api_client = create_api_client()
    result = get_remote_assignments(api_client)

    # Should be incomplete when users_ok is False
    assert result.is_complete is False
    assert len(result.assignments) == 0


@pytest.mark.django_db
def test_create_local_assignment_with_object():
    """Test create_local_assignment creates object-scoped assignment."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleUserAssignment
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple, create_local_assignment
    from test_app.models import Organization, User

    # Create user and organization with resources
    user = User.objects.create(username='testuser', email='test@example.com')
    user_resource = Resource.get_resource_for_object(user)
    org = Organization.objects.create(name='Test Org')
    org_resource = Resource.get_resource_for_object(org)
    org_dab_ct = DABContentType.objects.get_for_model(Organization)

    # Create role definition
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=org_dab_ct, managed=True)

    # Create assignment tuple for object-scoped assignment
    assignment_tuple = AssignmentTuple(
        actor_ansible_id=str(user_resource.ansible_id),
        ansible_id_or_pk=str(org_resource.ansible_id),
        role_definition_name='Org Admin',
        assignment_type='user',
    )

    # Create the assignment
    result = create_local_assignment(assignment_tuple)

    # Should return True and create the assignment
    assert result is True
    assert RoleUserAssignment.objects.filter(user=user, role_definition=role_def, object_id=org.pk).exists()


@pytest.mark.django_db
def test_create_local_assignment_global():
    """Test create_local_assignment creates global assignment."""
    from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple, create_local_assignment

    # Create user with resource
    user = User.objects.create(username='testuser', email='test@example.com')
    user_resource = Resource.get_resource_for_object(user)

    # Create global role definition (no content_type)
    role_def = RoleDefinition.objects.create(name='Global Admin', managed=True)

    # Create assignment tuple for global assignment (no ansible_id_or_pk)
    assignment_tuple = AssignmentTuple(
        actor_ansible_id=str(user_resource.ansible_id),
        ansible_id_or_pk=None,
        role_definition_name='Global Admin',
        assignment_type='user',
    )

    # Create the assignment
    result = create_local_assignment(assignment_tuple)

    # Should return True and create global assignment
    assert result is True
    assert RoleUserAssignment.objects.filter(user=user, role_definition=role_def, object_id__isnull=True).exists()


@pytest.mark.django_db
def test_create_local_assignment_for_team():
    """Test create_local_assignment creates team assignment."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleTeamAssignment
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple, create_local_assignment
    from test_app.models import Organization, Team

    # Create team and organization with resources
    org = Organization.objects.create(name='Test Org')
    team = Team.objects.create(name='Test Team', organization=org)
    team_resource = Resource.get_resource_for_object(team)
    target_org = Organization.objects.create(name='Target Org')
    target_org_resource = Resource.get_resource_for_object(target_org)
    org_dab_ct = DABContentType.objects.get_for_model(Organization)

    # Create role definition
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=org_dab_ct, managed=True)

    # Create assignment tuple for team assignment
    assignment_tuple = AssignmentTuple(
        actor_ansible_id=str(team_resource.ansible_id),
        ansible_id_or_pk=str(target_org_resource.ansible_id),
        role_definition_name='Org Admin',
        assignment_type='team',
    )

    # Create the assignment
    result = create_local_assignment(assignment_tuple)

    # Should return True and create the team assignment
    assert result is True
    assert RoleTeamAssignment.objects.filter(team=team, role_definition=role_def, object_id=target_org.pk).exists()


@pytest.mark.django_db
def test_delete_local_assignment_with_object():
    """Test delete_local_assignment removes object-scoped assignment."""
    from ansible_base.rbac.models import DABContentType, RoleDefinition
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple, delete_local_assignment
    from test_app.models import Organization, User

    # Create user and organization with resources
    user = User.objects.create(username='testuser', email='test@example.com')
    user_resource = Resource.get_resource_for_object(user)
    org = Organization.objects.create(name='Test Org')
    org_resource = Resource.get_resource_for_object(org)
    org_dab_ct = DABContentType.objects.get_for_model(Organization)

    # Create role and assignment
    role_def = RoleDefinition.objects.create(name='Org Admin', content_type=org_dab_ct, managed=True)
    role_def.give_permission(user, org)

    # Create assignment tuple for object-scoped assignment
    assignment_tuple = AssignmentTuple(
        actor_ansible_id=str(user_resource.ansible_id),
        ansible_id_or_pk=str(org_resource.ansible_id),
        role_definition_name='Org Admin',
        assignment_type='user',
    )

    # Delete the assignment
    result = delete_local_assignment(assignment_tuple)

    # Should return True and remove the assignment
    assert result is True
    from ansible_base.rbac.models import RoleUserAssignment

    assert not RoleUserAssignment.objects.filter(user=user, role_definition=role_def, object_id=org.pk).exists()


@pytest.mark.django_db
def test_delete_local_assignment_global():
    """Test delete_local_assignment removes global assignment"""
    from ansible_base.rbac.models import RoleDefinition
    from ansible_base.resource_registry.tasks.sync import AssignmentTuple, delete_local_assignment

    # Create user with resource
    user = User.objects.create(username='testuser', email='test@example.com')
    user_resource = Resource.get_resource_for_object(user)

    # Create global role and assignment
    role_def = RoleDefinition.objects.create(name='Global Admin', managed=True)
    role_def.give_global_permission(user)

    # Create assignment tuple for global assignment
    assignment_tuple = AssignmentTuple(
        actor_ansible_id=str(user_resource.ansible_id),
        ansible_id_or_pk=None,
        role_definition_name='Global Admin',
        assignment_type='user',
    )

    # Delete the assignment
    result = delete_local_assignment(assignment_tuple)

    # Should return True and remove global assignment
    assert result is True
    from ansible_base.rbac.models import RoleUserAssignment

    assert not RoleUserAssignment.objects.filter(user=user, role_definition=role_def, object_id__isnull=True).exists()


@pytest.mark.django_db
def test_cleanup_orphans_continues_after_deletion_error(admin_api_client, static_api_client, stdout):
    """Test that _cleanup_orphans skips a failing orphan, logs it and continues deleting the rest."""
    url = get_relative_url("resource-list")
    for username in ("orphan_one", "orphan_two"):
        response = admin_api_client.post(
            url,
            {
                "service_id": "57592fbc-7ecb-405f-9f5f-ebad20932d38",
                "resource_type": "shared.user",
                "resource_data": {"username": username, "last_name": "Test", "email": f"{username}@example.com"},
            },
            format="json",
        )
        assert response.status_code == 201

    with mock.patch("ansible_base.resource_registry.tasks.sync.delete_resource", side_effect=IntegrityError("FK constraint")):
        executor = SyncExecutor(api_client=static_api_client, stdout=stdout)
        executor.run()

    error_lines = [line for line in stdout.lines if "IntegrityError" in line]
    assert len(error_lines) == 2
    assert User.objects.filter(username__in=["orphan_one", "orphan_two"]).count() == 2
    assert executor.deleted_count == 0
