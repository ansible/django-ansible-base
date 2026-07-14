"""
Tests for the batch object deletion sync pipeline (AAP-82668).

Covers:
- ServiceObjectDeleteViewSet.batch_delete endpoint
- defer_rbac_cache accumulation of deleted_objects
- Batch flush to maybe_reverse_sync_object_deletions_batch on context exit
- Edge cases: empty lists, invalid types, mixed content types, sync disabled
- Performance regression: O(1) sync calls regardless of deletion count
"""

from unittest.mock import MagicMock, patch

import pytest
from django.db import connection

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.triggers import _defer_rbac_cache, defer_rbac_cache
from test_app.models import Inventory, Organization

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def second_org(db):
    return Organization.objects.create(name='batch-second-org')


@pytest.fixture
def second_inventory(second_org):
    return Inventory.objects.create(name='batch-second-inv', organization=second_org)


# ---------------------------------------------------------------------------
# 1. Batch endpoint accepts multiple deletions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_batch_endpoint_deletes_multiple_resources(admin_api_client, inventory, rando, inv_rd, second_inventory):
    """POST to object-delete/batch/ with multiple entries deletes all role assignments."""
    inv_rd.give_permission(rando, inventory)
    inv_rd.give_permission(rando, second_inventory)

    ct = permission_registry.content_type_model.objects.get_for_model(inventory)

    url = get_relative_url('serviceobjectdelete-list') + 'batch/'
    data = {
        'deletions': [
            {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(inventory.pk)},
            {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(second_inventory.pk)},
        ]
    }

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    assert response_data['deleted_count'] > 0

    # Verify both inventories' assignments are gone
    remaining = RoleUserAssignment.objects.filter(
        object_role__content_type=ct,
        object_role__object_id__in=[inventory.pk, second_inventory.pk],
    ).count()
    assert remaining == 0


# ---------------------------------------------------------------------------
# 2. Deferred sync accumulates objects
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_deferred_sync_accumulates_deleted_objects(organization, inventory, rando, inv_rd, second_inventory):
    """Inside defer_rbac_cache, deleting objects with role assignments accumulates
    entries in _defer_rbac_cache.deleted_objects during the block."""
    inv_rd.give_permission(rando, inventory)
    inv_rd.give_permission(rando, second_inventory)

    with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletions_batch'):
        with defer_rbac_cache():
            inventory.delete()
            second_inventory.delete()

            # During the block, deleted_objects should have accumulated entries
            assert len(_defer_rbac_cache.deleted_objects) >= 2


# ---------------------------------------------------------------------------
# 3. Deferred sync flushes batch on context exit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_deferred_sync_flushes_batch_on_exit(organization, inventory, rando, inv_rd, second_inventory):
    """Verify that maybe_reverse_sync_object_deletions_batch is called once
    with the accumulated list when the defer_rbac_cache context exits."""
    inv_rd.give_permission(rando, inventory)
    inv_rd.give_permission(rando, second_inventory)

    # Patch in_atomic_block to False so the sync fires immediately instead
    # of via on_commit (which is discarded in tests since transactions roll back)
    with patch('django.db.connection.in_atomic_block', False):
        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletions_batch') as mock_batch:
            with defer_rbac_cache():
                inventory.delete()
                second_inventory.delete()

                # Not called yet during the block
                mock_batch.assert_not_called()

            # Called exactly once after context exit
            mock_batch.assert_called_once()

            # The argument should be a list of tuples
            deleted_objects_arg = mock_batch.call_args[0][0]
            assert isinstance(deleted_objects_arg, list)
            assert len(deleted_objects_arg) >= 2
            # Each entry is (app_label, model, pk_string)
            for entry in deleted_objects_arg:
                assert len(entry) == 3


@pytest.mark.django_db(transaction=True)
def test_deferred_sync_fires_via_on_commit(organization, rando, inv_rd):
    """End-to-end test: verify the batch sync actually fires via
    transaction.on_commit when running inside a real transaction."""
    if connection.vendor == 'sqlite':
        pytest.skip('transaction=True tests require PostgreSQL')
    inv = Inventory.objects.create(name='on-commit-inv', organization=organization)
    inv_rd.give_permission(rando, inv)

    with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletions_batch') as mock_batch:
        from django.db import transaction

        with transaction.atomic():
            with defer_rbac_cache():
                inv.delete()
            # Still inside atomic -- on_commit hasn't fired yet
            mock_batch.assert_not_called()
        # Atomic block exited and committed -- on_commit fires
        mock_batch.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Single object delete still works
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_single_object_delete_endpoint_unchanged(admin_api_client, inventory, rando, inv_rd):
    """The non-batch object-delete/ endpoint still works as before."""
    inv_rd.give_permission(rando, inventory)

    ct = permission_registry.content_type_model.objects.get_for_model(inventory)
    url = get_relative_url('serviceobjectdelete-list')
    data = {
        'resource_type': f'{ct.app_label}.{ct.model}',
        'resource_pk': str(inventory.pk),
    }

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    assert response_data['deleted_count'] > 0
    assert 'breakdown' in response_data


# ---------------------------------------------------------------------------
# 5. Batch endpoint with empty list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_batch_endpoint_empty_list(admin_api_client):
    """POST with {"deletions": []} returns 400 (non-empty list required)."""
    url = get_relative_url('serviceobjectdelete-list') + 'batch/'
    data = {'deletions': []}

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 6. Batch endpoint with invalid resource_type
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_batch_endpoint_invalid_resource_type_skipped(admin_api_client, inventory, rando, inv_rd):
    """Malformed entries in the batch are skipped gracefully; valid entries
    still process correctly."""
    inv_rd.give_permission(rando, inventory)

    ct = permission_registry.content_type_model.objects.get_for_model(inventory)
    url = get_relative_url('serviceobjectdelete-list') + 'batch/'
    data = {
        'deletions': [
            # Invalid: no dot separator
            {'resource_type': 'badformat', 'resource_pk': '1'},
            # Invalid: unknown content type
            {'resource_type': 'nonexistent.model', 'resource_pk': '1'},
            # Invalid: missing fields
            {'resource_type': f'{ct.app_label}.{ct.model}'},
            # Valid entry
            {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(inventory.pk)},
        ]
    }

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    # The valid entry should still have been processed
    assert response_data['deleted_count'] > 0


# ---------------------------------------------------------------------------
# 7. Batch sync with sync disabled
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    'disable_method',
    ['reverse_sync_flag', 'env_var'],
    ids=['reverse_sync_disabled', 'env_var_disabled'],
)
def test_batch_sync_noop_when_disabled(organization, inventory, rando, inv_rd, disable_method):
    """maybe_reverse_sync_object_deletions_batch is a no-op when reverse sync
    is disabled, either via the global flag or the environment variable."""
    from ansible_base.rbac.sync import maybe_reverse_sync_object_deletions_batch

    inv_rd.give_permission(rando, inventory)

    deleted_objects = [('test_app', 'inventory', str(inventory.pk))]

    if disable_method == 'reverse_sync_flag':
        with patch('ansible_base.rbac.sync.reverse_sync_enabled_global', return_value=False):
            with patch('ansible_base.resource_registry.utils.sync_to_resource_server.get_current_user_resource_client') as mock_client:
                maybe_reverse_sync_object_deletions_batch(deleted_objects)
                mock_client.assert_not_called()

    elif disable_method == 'env_var':
        with patch('ansible_base.rbac.sync.reverse_sync_enabled_global', return_value=True):
            with patch.dict('os.environ', {'ANSIBLE_REVERSE_RESOURCE_SYNC': 'false'}):
                with patch('ansible_base.resource_registry.utils.sync_to_resource_server.get_current_user_resource_client') as mock_client:
                    maybe_reverse_sync_object_deletions_batch(deleted_objects)
                    mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Batch sync failure does not break deletion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_batch_sync_failure_does_not_break_deletion(organization, inventory, rando, inv_rd):
    """If the HTTP call in maybe_reverse_sync_object_deletions_batch fails,
    local deletion still succeeds."""
    inv_rd.give_permission(rando, inventory)
    inv_id = inventory.id

    # Patch in_atomic_block to False so the sync fires immediately
    with patch('django.db.connection.in_atomic_block', False):
        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletions_batch', side_effect=Exception('Gateway down')):
            with patch('ansible_base.rbac.triggers.logger') as mock_logger:
                with defer_rbac_cache():
                    inventory.delete()

                # Exception should be logged
                mock_logger.exception.assert_called_once()

    # Local deletion still succeeded
    assert not Inventory.objects.filter(id=inv_id).exists()


# ---------------------------------------------------------------------------
# 9. Batch with mixed content types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_batch_endpoint_mixed_content_types(admin_api_client, inventory, organization, rando, inv_rd, org_admin_rd):
    """Batch delete handles objects of different types (inventory + organization)
    in a single request."""
    inv_rd.give_permission(rando, inventory)
    org_admin_rd.give_permission(rando, organization)

    ct_inv = permission_registry.content_type_model.objects.get_for_model(inventory)
    ct_org = permission_registry.content_type_model.objects.get_for_model(organization)

    url = get_relative_url('serviceobjectdelete-list') + 'batch/'
    data = {
        'deletions': [
            {'resource_type': f'{ct_inv.app_label}.{ct_inv.model}', 'resource_pk': str(inventory.pk)},
            {'resource_type': f'{ct_org.app_label}.{ct_org.model}', 'resource_pk': str(organization.pk)},
        ]
    }

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    assert response_data['deleted_count'] > 0

    # Both types of assignments should be cleaned up
    remaining_inv = RoleUserAssignment.objects.filter(
        object_role__content_type=ct_inv,
        object_role__object_id=inventory.pk,
    ).count()
    remaining_org = RoleUserAssignment.objects.filter(
        object_role__content_type=ct_org,
        object_role__object_id=organization.pk,
    ).count()
    assert remaining_inv == 0
    assert remaining_org == 0


# ---------------------------------------------------------------------------
# 10. Without defer, sync calls are per-object
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_without_defer_sync_calls_per_object(organization, rando, inv_rd):
    """Without defer_rbac_cache, maybe_reverse_sync_object_deletion (singular)
    is called per object in the non-deferred code path of the signal handler."""
    inv1 = Inventory.objects.create(name='per-obj-1', organization=organization)
    inv2 = Inventory.objects.create(name='per-obj-2', organization=organization)
    inv_rd.give_permission(rando, inv1)
    inv_rd.give_permission(rando, inv2)

    # The model's .delete() wraps itself in defer_rbac_cache, so to test
    # the non-deferred signal path directly we call the signal handler
    # with _defer_rbac_cache.active = False (its default state).
    # We need the ObjectRoles to exist so had_object_assignments is True.
    with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_single:
        from ansible_base.rbac.triggers import rbac_post_delete_remove_object_roles

        # Directly invoke the signal handler with defer inactive (default state).
        # The signal handler will delete ObjectRoles from DB and check the count.
        rbac_post_delete_remove_object_roles(inv1)
        rbac_post_delete_remove_object_roles(inv2)

    assert mock_single.call_count == 2
    # Verify each call received the correct instance
    call_instances = [c[0][0] for c in mock_single.call_args_list]
    assert inv1 in call_instances
    assert inv2 in call_instances


# ---------------------------------------------------------------------------
# 11. Sync call count stays O(1) -- parameterized perf regression test
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize('num_objects', [1, 5, 10], ids=['n=1', 'n=5', 'n=10'])
def test_sync_call_count_stays_constant(organization, rando, inv_rd, num_objects):
    """Deleting N objects inside defer_rbac_cache results in exactly one batch
    sync call, regardless of N."""
    inventories = [Inventory.objects.create(name=f'perf-inv-{i}', organization=organization) for i in range(num_objects)]
    for inv in inventories:
        inv_rd.give_permission(rando, inv)

    # Patch in_atomic_block to False so the sync fires immediately
    with patch('django.db.connection.in_atomic_block', False):
        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletions_batch') as mock_batch:
            with defer_rbac_cache():
                for inv in inventories:
                    inv.delete()

                # Not called during the block
                mock_batch.assert_not_called()

            # Called exactly once after context exit, regardless of num_objects
            mock_batch.assert_called_once()

            # The single call should contain all deleted objects
            deleted_objects_arg = mock_batch.call_args[0][0]
            assert len(deleted_objects_arg) == num_objects


# ---------------------------------------------------------------------------
# 12. reverse_sync_enabled_global() direct unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'enabled_flag,should_sync,expected',
    [
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
    ids=['flag-disabled', 'should-sync-false', 'both-enabled'],
)
def test_reverse_sync_enabled_global(enabled_flag, should_sync, expected):
    """Exercise reverse_sync_enabled_global() directly to cover all branch
    combinations of the global enabled flag and _should_reverse_sync()."""
    from ansible_base.rbac.sync import reverse_sync_enabled_global

    mock_flag = MagicMock()
    mock_flag.enabled = enabled_flag
    with patch('ansible_base.resource_registry.signals.handlers.reverse_sync_enabled', mock_flag):
        with patch('ansible_base.resource_registry.apps._should_reverse_sync', return_value=should_sync):
            assert reverse_sync_enabled_global() is expected


# ---------------------------------------------------------------------------
# 13. maybe_reverse_sync_object_deletions_batch() -- comprehensive coverage
# ---------------------------------------------------------------------------


def test_batch_sync_empty_list_returns_immediately():
    """Passing an empty list should return without calling any sync logic."""
    from ansible_base.rbac.sync import maybe_reverse_sync_object_deletions_batch

    with patch('ansible_base.rbac.sync.reverse_sync_enabled_global') as mock_global:
        maybe_reverse_sync_object_deletions_batch([])
        mock_global.assert_not_called()


def test_batch_sync_success_path():
    """When sync is enabled and the client returns a success dict,
    the function completes without warnings."""
    from ansible_base.rbac.sync import maybe_reverse_sync_object_deletions_batch

    mock_client = MagicMock()
    mock_client.sync_object_deletions_batch.return_value = {'deleted_count': 2}

    with patch('ansible_base.rbac.sync.reverse_sync_enabled_global', return_value=True):
        with patch.dict('os.environ', {'ANSIBLE_REVERSE_RESOURCE_SYNC': 'true'}):
            with patch(
                'ansible_base.resource_registry.utils.sync_to_resource_server.get_current_user_resource_client',
                return_value=mock_client,
            ):
                maybe_reverse_sync_object_deletions_batch([('app', 'model', '1'), ('app', 'model', '2')])

    mock_client.sync_object_deletions_batch.assert_called_once_with([('app', 'model', '1'), ('app', 'model', '2')])


def test_batch_sync_error_response_logs_warning():
    """When the client returns an error dict, the function logs a warning."""
    from ansible_base.rbac.sync import maybe_reverse_sync_object_deletions_batch

    mock_client = MagicMock()
    mock_client.sync_object_deletions_batch.return_value = {'error': 'Failed with status 500', 'status_code': 500}

    with patch('ansible_base.rbac.sync.reverse_sync_enabled_global', return_value=True):
        with patch.dict('os.environ', {'ANSIBLE_REVERSE_RESOURCE_SYNC': 'true'}):
            with patch(
                'ansible_base.resource_registry.utils.sync_to_resource_server.get_current_user_resource_client',
                return_value=mock_client,
            ):
                with patch('ansible_base.rbac.sync.logger') as mock_logger:
                    maybe_reverse_sync_object_deletions_batch([('app', 'model', '1')])
                    mock_logger.warning.assert_called_once()


def test_batch_sync_exception_logs_and_continues():
    """When the client raises an exception, the function catches it and logs
    via logger.exception without re-raising."""
    from ansible_base.rbac.sync import maybe_reverse_sync_object_deletions_batch

    mock_client = MagicMock()
    mock_client.sync_object_deletions_batch.side_effect = Exception('Connection refused')

    with patch('ansible_base.rbac.sync.reverse_sync_enabled_global', return_value=True):
        with patch.dict('os.environ', {'ANSIBLE_REVERSE_RESOURCE_SYNC': 'true'}):
            with patch(
                'ansible_base.resource_registry.utils.sync_to_resource_server.get_current_user_resource_client',
                return_value=mock_client,
            ):
                with patch('ansible_base.rbac.sync.logger') as mock_logger:
                    maybe_reverse_sync_object_deletions_batch([('app', 'model', '1')])
                    mock_logger.exception.assert_called_once()


# ---------------------------------------------------------------------------
# 14. Batch endpoint -- invalid entry types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    'invalid_entry',
    [
        42,
        'a-string',
        {'resource_pk': '1'},
        {'resource_type': None, 'resource_pk': '1'},
    ],
    ids=['non-dict-int', 'non-dict-str', 'missing-resource-type', 'null-resource-type'],
)
def test_batch_endpoint_invalid_entry_skipped_valid_processed(admin_api_client, inventory, rando, inv_rd, invalid_entry):
    """Invalid entries (non-dict, missing fields, null resource_type) are
    skipped; valid entries in the same batch still process correctly."""
    inv_rd.give_permission(rando, inventory)
    ct = permission_registry.content_type_model.objects.get_for_model(inventory)

    url = get_relative_url('serviceobjectdelete-list') + 'batch/'
    data = {
        'deletions': [
            invalid_entry,
            {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(inventory.pk)},
        ]
    }

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200
    assert response.json()['deleted_count'] > 0


@pytest.mark.django_db
def test_batch_endpoint_all_unknown_content_types(admin_api_client):
    """When every entry references an unknown content type, the endpoint
    returns deleted_count=0 with a descriptive message."""
    url = get_relative_url('serviceobjectdelete-list') + 'batch/'
    data = {
        'deletions': [
            {'resource_type': 'nonexistent.model', 'resource_pk': '1'},
            {'resource_type': 'also_nonexistent.thing', 'resource_pk': '2'},
        ]
    }

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200
    assert response.json()['deleted_count'] == 0
    assert 'No valid content types' in response.json()['message']


# ---------------------------------------------------------------------------
# 15. _bulk_pre_cascade_rbac_cleanup defensive guard
# ---------------------------------------------------------------------------


def test_bulk_pre_cascade_noop_when_not_deferred():
    """_bulk_pre_cascade_rbac_cleanup is a no-op when defer_rbac_cache is not
    active, covering the defensive early-return branch."""
    from ansible_base.rbac.triggers import _bulk_pre_cascade_rbac_cleanup

    assert not _defer_rbac_cache.active
    # When defer is inactive the function returns immediately.
    # Passing a MagicMock proves it never queries for child models.
    _bulk_pre_cascade_rbac_cleanup(MagicMock())
