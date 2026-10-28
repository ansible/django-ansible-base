from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from zlib import crc32

import pytest
from django.db import OperationalError
from django.test import override_settings

from ansible_base.lib.utils import db


def make_mssql_connection(monkeypatch, result, raw_connection=object(), execute_error=None):
    cursor = Mock()
    cursor.fetchone.return_value = result
    if execute_error is not None:
        cursor.execute.side_effect = execute_error

    connection = Mock()
    connection.connection = raw_connection
    connection.cursor.return_value = cursor
    monkeypatch.setattr(db, 'connections', {'default': connection, 'replica': connection})
    return connection, cursor


@pytest.mark.parametrize(
    ('lock_id', 'expected'),
    [
        ('short_name', 'short_name'),
        ('x' * 260, 'x' * 255),
        (12, 'dab_lock_12'),
        ([1, 2], 'dab_lock_1_2'),
        ((3, 4), 'dab_lock_3_4'),
    ],
)
def test_convert_lock_id_to_sql_server_resource_name(lock_id, expected):
    assert db._convert_lock_id_to_resource_name(lock_id) == expected


def test_convert_lock_id_hashes_other_types():
    lock_id = SimpleNamespace(name='lock')
    expected = f'dab_lock_{crc32(str(lock_id).encode("utf-8"))}'

    assert db._convert_lock_id_to_resource_name(lock_id) == expected


@pytest.mark.parametrize('lock_id', [(1,), ('a', 'b'), [1, 2, 3]])
def test_convert_lock_id_rejects_invalid_sequences(lock_id):
    with pytest.raises(ValueError):
        db._convert_lock_id_to_resource_name(lock_id)


def test_mssql_advisory_lock_acquires_and_releases(monkeypatch):
    connection, cursor = make_mssql_connection(monkeypatch, (0,), raw_connection=None)

    with db._mssql_advisory_lock((12, 34), shared=True, lock_session_timeout_milliseconds=500, using='replica') as acquired:
        assert acquired is True

    connection.ensure_connection.assert_called_once()
    assert cursor.execute.call_count == 2
    assert cursor.execute.call_args_list[0].args[1] == ['dab_lock_12_34', 'Shared', 500]
    assert cursor.execute.call_args_list[1].args[1] == ['dab_lock_12_34']
    cursor.close.assert_called_once()


def test_mssql_advisory_lock_timeout_returns_not_acquired_when_not_waiting(monkeypatch):
    _, cursor = make_mssql_connection(monkeypatch, (-1,))

    with db._mssql_advisory_lock('lock', wait=False) as acquired:
        assert acquired is False

    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[1] == ['lock', 'Exclusive', 0]


def test_mssql_advisory_lock_timeout_raises_when_waiting(monkeypatch):
    _, cursor = make_mssql_connection(monkeypatch, (-1,))

    with pytest.raises(OperationalError, match='timed out'):
        with db._mssql_advisory_lock('lock', wait=True, lock_session_timeout_milliseconds=500):
            pytest.fail('waiting lock acquisition should raise after timing out')

    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[1] == ['lock', 'Exclusive', 500]
    cursor.close.assert_called_once()


@pytest.mark.parametrize(('row', 'code'), [(None, -999), ((-3,), -3)])
def test_mssql_advisory_lock_raises_for_failed_acquisition(monkeypatch, row, code):
    _, cursor = make_mssql_connection(monkeypatch, row)

    with pytest.raises(OperationalError, match=str(code)):
        with db._mssql_advisory_lock('lock'):
            pytest.fail('lock acquisition should fail')

    cursor.close.assert_called_once()
    assert cursor.execute.call_count == 1


def test_mssql_advisory_lock_wraps_execute_errors(monkeypatch):
    _, cursor = make_mssql_connection(monkeypatch, None, execute_error=RuntimeError('connection failed'))
    logger = Mock()
    monkeypatch.setattr(db, 'logger', logger)

    with pytest.raises(OperationalError, match='-999'):
        with db._mssql_advisory_lock('lock'):
            pytest.fail('lock acquisition should fail')

    logger.exception.assert_called_once()
    cursor.close.assert_called_once()


def test_advisory_lock_dispatches_to_mssql_and_passes_options(monkeypatch):
    connection = SimpleNamespace(vendor='microsoft', close_if_unusable_or_obsolete=Mock())
    monkeypatch.setattr(db, 'connection', connection)
    called = {}

    @contextmanager
    def fake_mssql_lock(lock_id, **kwargs):
        called['lock_id'] = lock_id
        called['kwargs'] = kwargs
        yield True

    monkeypatch.setattr(db, '_mssql_advisory_lock', fake_mssql_lock)
    with db.advisory_lock('lock', shared=True, wait=False, lock_session_timeout_milliseconds=5, using='replica') as acquired:
        assert acquired is True

    assert called == {
        'lock_id': 'lock',
        'kwargs': {'shared': True, 'wait': False, 'lock_session_timeout_milliseconds': 5, 'using': 'replica'},
    }


def test_advisory_lock_closes_connection_after_mssql_error(monkeypatch):
    connection = SimpleNamespace(vendor='microsoft', close_if_unusable_or_obsolete=Mock())
    monkeypatch.setattr(db, 'connection', connection)

    class FailedLock:
        def __enter__(self):
            raise OperationalError('lock failed')

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(db, '_mssql_advisory_lock', lambda *args, **kwargs: FailedLock())
    with pytest.raises(OperationalError, match='lock failed'):
        with db.advisory_lock('lock'):
            pass

    connection.close_if_unusable_or_obsolete.assert_called_once()


def test_advisory_lock_requires_lock_id_for_mssql(monkeypatch):
    monkeypatch.setattr(db, 'connection', SimpleNamespace(vendor='microsoft'))

    with pytest.raises(ValueError, match='lock identifier'):
        with db.advisory_lock():
            pass


def test_get_sql_server_notify_params_applies_overrides_and_options():
    databases = {
        'default': {
            'ENGINE': 'ansible_base.backends.mssql',
            'HOST': 'database.example',
            'PORT': 1434,
            'NAME': 'main',
            'USER': 'user',
            'PASSWORD': 'password',
            'OPTIONS': {'driver': 'ODBC Driver'},
        }
    }
    overrides = {'default': {'HOST': 'listener.example', 'OPTIONS': {'Encrypt': 'yes'}}}
    with override_settings(DATABASES=databases, SQL_SERVER_NOTIFY_DATABASES=overrides):
        params = db.get_sql_server_notify_params(application_name='dispatcherd')

    assert params == {
        'server': 'listener.example',
        'port': 1434,
        'database': 'main',
        'user': 'user',
        'password': 'password',
        'driver': 'ODBC Driver',
        'application_name': 'dispatcherd',
        'Encrypt': 'yes',
    }


def test_get_sql_server_notify_params_uses_host_and_port_defaults(monkeypatch):
    databases = {'replica': {'ENGINE': 'ansible_base.backends.mssql', 'NAME': 'replica_db'}}
    monkeypatch.setattr(db, 'combine_settings_dict', lambda *args, **kwargs: {'HOST': '', 'PORT': '', 'NAME': 'replica_db'})
    with override_settings(DATABASES=databases):
        params = db.get_sql_server_notify_params(alias='replica')

    assert params == {'server': 'localhost', 'port': 1433, 'database': 'replica_db', 'user': None, 'password': None}
