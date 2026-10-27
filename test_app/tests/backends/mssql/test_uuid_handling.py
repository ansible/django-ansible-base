import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils.encoding import smart_str
from mssql.operations import DatabaseOperations as MSSQLDatabaseOperations

from ansible_base.backends.mssql.base import DatabaseWrapper
from ansible_base.backends.mssql.cursor_override import CursorWrapper
from ansible_base.backends.mssql.operations import DatabaseOperations
from ansible_base.backends.mssql.schema import DatabaseSchemaEditor
from ansible_base.backends.mssql.signals import setup_uuid_handling


def make_cursor_wrapper(driver_charset=None):
    return CursorWrapper(Mock(), Mock(driver_charset=driver_charset))


def test_format_params_none_returns_empty_tuple():
    assert make_cursor_wrapper().format_params(None) == ()


def test_format_params_applies_driver_charset_to_strings():
    wrapper = make_cursor_wrapper(driver_charset='utf-8')

    assert wrapper.format_params(['hello']) == (smart_str('hello', 'utf-8'),)


def test_format_params_preserves_string_without_driver_charset():
    value = 'hello'

    assert make_cursor_wrapper().format_params([value]) == (value,)


def test_format_params_preserves_bytes_and_non_uuid_values():
    values = [b'bytes', 42]

    assert make_cursor_wrapper().format_params(values) == tuple(values)


def test_format_params_converts_booleans_and_uuids():
    value = uuid.uuid4()

    assert make_cursor_wrapper().format_params([True, False, value]) == (1, 0, value.hex)


def test_database_wrapper_uses_custom_backend_components():
    assert DatabaseWrapper.SchemaEditorClass is DatabaseSchemaEditor
    assert DatabaseWrapper.ops_class is DatabaseOperations
    assert 'JSONField' not in DatabaseWrapper.data_type_check_constraints
    assert DatabaseWrapper.data_type_check_constraints['PositiveIntegerField'] == '[%(column)s] >= 0'


def test_database_wrapper_create_cursor_uses_uuid_cursor_wrapper():
    wrapper = DatabaseWrapper.__new__(DatabaseWrapper)
    raw_cursor = Mock()
    wrapper.connection = Mock()
    wrapper.connection.cursor.return_value = raw_cursor
    wrapper.driver_charset = None

    cursor = wrapper.create_cursor()

    assert isinstance(cursor, CursorWrapper)
    assert cursor.cursor is raw_cursor
    assert cursor.connection is wrapper


def test_database_operations_inherits_mssql_defaults():
    assert issubclass(DatabaseOperations, MSSQLDatabaseOperations)


def test_setup_uuid_handling_registers_guid_converter():
    raw_connection = Mock()
    connection = SimpleNamespace(vendor='microsoft', connection=raw_connection)

    setup_uuid_handling(None, connection)

    raw_connection.add_output_converter.assert_called_once()
    sql_type, converter = raw_connection.add_output_converter.call_args.args
    assert sql_type == -11

    value = uuid.uuid4()
    assert converter(None) is None
    assert converter(value) is value
    assert converter(value.bytes_le) == value
    assert converter(str(value)) == value
    other = object()
    assert converter(other) is other


def test_setup_uuid_handling_ignores_non_microsoft_connections():
    raw_connection = Mock()

    setup_uuid_handling(None, SimpleNamespace(vendor='postgresql', connection=raw_connection))

    raw_connection.add_output_converter.assert_not_called()


@pytest.mark.parametrize('raw_connection', [None, object()])
def test_setup_uuid_handling_ignores_connections_without_converter(raw_connection):
    setup_uuid_handling(None, SimpleNamespace(vendor='microsoft', connection=raw_connection))
