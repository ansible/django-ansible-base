from unittest import mock

import pytest

from ansible_base.resource_registry.models import Resource
from ansible_base.resource_registry.signals import handlers
from ansible_base.resource_registry.signals.handlers import defer_resource_cleanup
from test_app.models import EncryptionModel, Organization, Original1, Original2, Proxy1, Proxy2


@pytest.mark.django_db
def test_unregistered_model_triggers_no_signals():
    with mock.patch('ansible_base.resource_registry.models.resource.init_resource_from_object') as mck:
        obj = EncryptionModel.objects.create()
    mck.assert_not_called()

    with mock.patch('ansible_base.resource_registry.models.Resource.update_from_content_object') as mck:
        obj.a = 'foobar'
        obj.save()
    mck.assert_not_called()

    with mock.patch('ansible_base.resource_registry.models.Resource.delete') as mck:
        obj.delete()
    mck.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize('model', [Organization, Original1, Original2, Proxy1, Proxy2])
def test_registered_model_triggers_signals(model, system_user):
    with mock.patch('ansible_base.resource_registry.signals.handlers.init_resource_from_object', wraps=handlers.init_resource_from_object) as mck:
        obj = model.objects.create(name='foo')
    mck.assert_called_once_with(obj)

    with mock.patch('ansible_base.resource_registry.models.Resource.update_from_content_object') as mck:
        obj.description = 'foobar'
        obj.save()
    mck.assert_called_once_with()

    with mock.patch('ansible_base.resource_registry.models.Resource.delete') as mck:
        obj.delete()
    mck.assert_called_once_with()


@pytest.mark.django_db
def test_decide_to_sync_update_skips_class_level_flag(organization, monkeypatch):
    """decide_to_sync_update returns before touching serializer_class when the model sets the flag at the class level.

    Models registered without a managed_serializer (serializer_class=None) set
    _skip_reverse_resource_sync=True on the class to opt out of reverse sync.
    The handler must bail before calling serializer_class(), which raises TypeError when None.

    Without this fix, the handler would reach serializer_class().get_fields() and raise:
        TypeError: 'NoneType' object is not callable
    """
    monkeypatch.setattr(Organization, '_skip_reverse_resource_sync', True, raising=False)
    with mock.patch.object(handlers, 'Resource') as mock_resource:
        organization.name = 'changed'
        handlers.decide_to_sync_update(
            sender=Organization,
            instance=organization,
            raw=False,
            using='default',
            update_fields=None,
        )
    mock_resource.get_resource_for_object.assert_not_called()


@pytest.mark.django_db
def test_pre_delete_sync_skips_class_level_flag(organization, monkeypatch):
    """sync_to_resource_server_pre_delete returns early when the model sets the flag at the class level.

    Models that opt out of reverse sync must not trigger a Gateway sync on delete.
    The flag check must occur before any Resource lookup or sync_to_resource_server call.

    Without this fix, the handler would reach instance.resource.ansible_id and raise:
        AttributeError: '<Model>' object has no attribute 'resource'
    (Resource uses GenericForeignKey — no automatic reverse accessor exists on the instance.)
    """
    monkeypatch.setattr(Organization, '_skip_reverse_resource_sync', True, raising=False)
    with mock.patch('ansible_base.resource_registry.signals.handlers.sync_to_resource_server') as mock_sync:
        handlers.sync_to_resource_server_pre_delete(sender=Organization, instance=organization)
    mock_sync.assert_not_called()


@pytest.mark.django_db
def test_pre_delete_sync_resource_not_found(organization):
    """sync_to_resource_server_pre_delete logs a warning and skips sync when the Resource row is absent."""
    with (
        mock.patch.object(handlers, 'Resource') as mock_resource,
        mock.patch('ansible_base.resource_registry.signals.handlers.sync_to_resource_server') as mock_sync,
    ):
        mock_resource.DoesNotExist = Resource.DoesNotExist
        mock_resource.get_resource_for_object.side_effect = Resource.DoesNotExist
        handlers.sync_to_resource_server_pre_delete(sender=Organization, instance=organization)
    mock_sync.assert_not_called()


@pytest.mark.django_db
def test_pre_delete_sync_calls_sync_to_resource_server(organization):
    """sync_to_resource_server_pre_delete passes the resource ansible_id to sync_to_resource_server."""
    mock_resource_obj = mock.MagicMock()
    mock_resource_obj.ansible_id = 'test-ansible-id-123'
    with (
        mock.patch.object(handlers, 'Resource') as mock_resource,
        mock.patch('ansible_base.resource_registry.signals.handlers.sync_to_resource_server') as mock_sync,
    ):
        mock_resource.DoesNotExist = Resource.DoesNotExist
        mock_resource.get_resource_for_object.return_value = mock_resource_obj
        handlers.sync_to_resource_server_pre_delete(sender=Organization, instance=organization)
    mock_sync.assert_called_once_with(organization, "delete", ansible_id='test-ansible-id-123')


@pytest.mark.django_db
def test_decide_to_sync_update_with_create(enable_reverse_sync):
    with enable_reverse_sync(mock_away_sync=True):
        org = Organization.objects.create(name='Hello')

    assert not hasattr(org, '_skip_reverse_resource_sync')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'fields, update_fields, should_skip',
    [
        (['name'], ['name'], False),
        (['name'], ['description'], False),
        (['name'], None, False),
        (['extra_field'], ['extra_field'], True),
        (['extra_field', 'name'], ['name', 'extra_field'], False),
        (['extra_field'], None, True),
    ],
)
def test_decide_to_sync_update_save(organization, enable_reverse_sync, fields, update_fields, should_skip):
    with enable_reverse_sync(mock_away_sync=True):
        for field in fields:
            setattr(organization, field, 'newvalue')
        organization.save(update_fields=update_fields)

    assert hasattr(organization, '_skip_reverse_resource_sync') == should_skip


def _cleanup_with_exception(org):
    """Helper to ensure only one throwing invocation inside pytest.raises."""
    with defer_resource_cleanup():
        org.delete()
        raise RuntimeError("deliberate")


@pytest.mark.django_db
def test_defer_resource_cleanup_flushes_on_exception(system_user):
    """On exception, deferred resource cleanup should still flush."""
    org = Organization.objects.create(name='cleanup-exc-org')
    assert Resource.objects.filter(object_id=org.pk).exists()

    with pytest.raises(RuntimeError, match="deliberate"):
        _cleanup_with_exception(org)

    assert not Resource.objects.filter(object_id=org.pk).exists()


def _nested_resource_cleanup():
    """Helper to ensure only one throwing invocation inside pytest.raises."""
    with defer_resource_cleanup():
        with defer_resource_cleanup():
            pass


@pytest.mark.django_db
def test_defer_resource_cleanup_cannot_nest():
    """Nesting defer_resource_cleanup should raise RuntimeError."""
    with pytest.raises(RuntimeError, match="cannot be nested"):
        _nested_resource_cleanup()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param("rollback", id="skips_flush_on_rollback"),
        pytest.param("flush_error", id="suppresses_flush_exception"),
    ],
)
def test_defer_resource_cleanup_error_handling(system_user, scenario):
    """Rollback and flush-error paths in defer_resource_cleanup's exception handler."""
    org = Organization.objects.create(name=f'cleanup-{scenario}-org')

    def _delete_and_raise():
        with defer_resource_cleanup():
            org.delete()
            raise RuntimeError("deliberate")

    if scenario == "rollback":
        with mock.patch('ansible_base.resource_registry.signals.handlers.connection') as mock_conn:
            mock_conn.in_atomic_block = True
            mock_conn.needs_rollback = True
            with pytest.raises(RuntimeError, match="deliberate"):
                _delete_and_raise()
    else:
        with mock.patch('ansible_base.resource_registry.signals.handlers._flush_pending_resources', side_effect=RuntimeError("flush error")):
            with pytest.raises(RuntimeError, match="deliberate"):
                _delete_and_raise()
