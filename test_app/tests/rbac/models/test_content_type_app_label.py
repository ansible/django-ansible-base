"""Tests for shared content type app_label resolution.

Covers _find_shared_model_app_label, load_remote_objects app_label fix,
and model_class() fallback to remote stand-in.
"""

from unittest.mock import MagicMock, patch

import pytest

from ansible_base.rbac.models import DABContentType
from ansible_base.rbac.models.content_type import _find_shared_model_app_label
from ansible_base.rbac.remote import RemoteObject


# -- _find_shared_model_app_label tests --


def test_find_shared_model_app_label_returns_match():
    """When the resource registry has a shared model matching model_name, return its app_label."""
    mock_config = MagicMock()
    mock_config.managed_serializer = True
    mock_config.model._meta.model_name = 'user'
    mock_config.model._meta.app_label = 'my_app'

    mock_registry = MagicMock()
    mock_registry.get_resources.return_value = {'my_app.User': mock_config}

    with patch('ansible_base.rbac.remote.get_resource_registry', return_value=mock_registry):
        assert _find_shared_model_app_label('user') == 'my_app'


def test_find_shared_model_app_label_no_match():
    """When no shared model matches model_name, return None."""
    mock_config = MagicMock()
    mock_config.managed_serializer = True
    mock_config.model._meta.model_name = 'organization'
    mock_config.model._meta.app_label = 'my_app'

    mock_registry = MagicMock()
    mock_registry.get_resources.return_value = {'my_app.Organization': mock_config}

    with patch('ansible_base.rbac.remote.get_resource_registry', return_value=mock_registry):
        assert _find_shared_model_app_label('user') is None


def test_find_shared_model_app_label_skips_non_shared():
    """Models without managed_serializer (not shared) should be skipped."""
    mock_config = MagicMock()
    mock_config.managed_serializer = None
    mock_config.model._meta.model_name = 'user'
    mock_config.model._meta.app_label = 'my_app'

    mock_registry = MagicMock()
    mock_registry.get_resources.return_value = {'my_app.User': mock_config}

    with patch('ansible_base.rbac.remote.get_resource_registry', return_value=mock_registry):
        assert _find_shared_model_app_label('user') is None


def test_find_shared_model_app_label_no_registry():
    """When no resource registry is configured, return None."""
    with patch('ansible_base.rbac.remote.get_resource_registry', return_value=None):
        assert _find_shared_model_app_label('user') is None


def test_find_shared_model_app_label_empty_registry():
    """When the resource registry has no models, return None."""
    mock_registry = MagicMock()
    mock_registry.get_resources.return_value = {}

    with patch('ansible_base.rbac.remote.get_resource_registry', return_value=mock_registry):
        assert _find_shared_model_app_label('user') is None


# -- model_class() fallback tests --


@pytest.mark.django_db
def test_model_class_returns_standin_for_unresolvable_shared_type():
    """A shared content type with a foreign app_label should return a remote stand-in, not raise."""
    ct = DABContentType.objects.create(
        service='shared',
        app_label='nonexistent_app',
        model='somemodel',
    )
    result = ct.model_class()
    assert issubclass(result, RemoteObject)


@pytest.mark.django_db
def test_model_class_returns_standin_for_unresolvable_local_type():
    """A local content type with a bad app_label should also return a remote stand-in."""
    ct = DABContentType.objects.create(
        service='aap',
        app_label='nonexistent_app',
        model='somemodel',
    )
    result = ct.model_class()
    assert issubclass(result, RemoteObject)


@pytest.mark.django_db
def test_model_class_logs_error_for_unresolvable_type(caplog):
    """Falling back to remote stand-in should log an error."""
    ct = DABContentType.objects.create(
        service='shared',
        app_label='fake_app',
        model='fakemodel',
    )
    with caplog.at_level('ERROR', logger='ansible_base.rbac.models.content_type'):
        ct.model_class()
    assert 'fake_app' in caplog.text
    assert 'fakemodel' in caplog.text
    assert 'Falling back to remote stand-in' in caplog.text


@pytest.mark.django_db
def test_model_class_valid_shared_type_still_works():
    """A shared content type with a valid app_label should still return the real model class."""
    from test_app.models import Organization

    ct = DABContentType.objects.get(service='shared', model='organization')
    result = ct.model_class()
    assert result is Organization


@pytest.mark.django_db
def test_model_class_remote_service_still_returns_standin():
    """Content types from remote services should still return remote stand-ins as before."""
    ct = DABContentType.objects.create(
        service='eda',
        app_label='core',
        model='user',
    )
    result = ct.model_class()
    assert issubclass(result, RemoteObject)


# -- load_remote_objects app_label resolution tests --


@pytest.mark.django_db
def test_load_remote_objects_resolves_local_app_label_for_shared_type():
    """When a shared content type has a foreign app_label, load_remote_objects should
    resolve it to the local app_label via the resource registry."""
    DABContentType.objects.filter(service='shared', model='user').delete()

    remote_data = [
        {
            'service': 'shared',
            'app_label': 'core',
            'model': 'user',
            'parent_content_type': None,
            'pk_field_type': 'integer',
        },
    ]
    DABContentType.objects.load_remote_objects(remote_data)
    ct = DABContentType.objects.get(service='shared', model='user')
    assert ct.app_label == 'test_app'


@pytest.mark.django_db
def test_load_remote_objects_keeps_valid_app_label():
    """When a shared content type already has a valid local app_label, don't change it."""
    DABContentType.objects.filter(service='shared', model='organization').delete()

    remote_data = [
        {
            'service': 'shared',
            'app_label': 'test_app',
            'model': 'organization',
            'parent_content_type': None,
            'pk_field_type': 'integer',
        },
    ]
    DABContentType.objects.load_remote_objects(remote_data)
    ct = DABContentType.objects.get(service='shared', model='organization')
    assert ct.app_label == 'test_app'


@pytest.mark.django_db
def test_load_remote_objects_non_shared_type_keeps_remote_app_label():
    """Non-shared content types should keep the remote app_label as-is."""
    remote_data = [
        {
            'service': 'eda',
            'app_label': 'core',
            'model': 'activation',
            'parent_content_type': None,
            'pk_field_type': 'integer',
        },
    ]
    DABContentType.objects.load_remote_objects(remote_data)
    ct = DABContentType.objects.get(service='eda', model='activation')
    assert ct.app_label == 'core'


@pytest.mark.django_db
def test_load_remote_objects_shared_type_no_registry_match_keeps_remote():
    """When the resource registry has no match for a shared model, keep the remote app_label."""
    remote_data = [
        {
            'service': 'shared',
            'app_label': 'foreign_app',
            'model': 'unknown_shared_model',
            'parent_content_type': None,
            'pk_field_type': 'integer',
        },
    ]
    DABContentType.objects.load_remote_objects(remote_data)
    ct = DABContentType.objects.get(service='shared', model='unknown_shared_model')
    assert ct.app_label == 'foreign_app'


@pytest.mark.django_db
def test_load_remote_objects_existing_row_not_overwritten():
    """If a shared content type already exists, get_or_create should not overwrite the app_label."""
    ct = DABContentType.objects.get(service='shared', model='organization')
    original_app_label = ct.app_label

    remote_data = [
        {
            'service': 'shared',
            'app_label': 'core',
            'model': 'organization',
            'parent_content_type': None,
            'pk_field_type': 'integer',
        },
    ]
    DABContentType.objects.load_remote_objects(remote_data)
    ct.refresh_from_db()
    assert ct.app_label == original_app_label
