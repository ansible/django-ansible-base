import uuid
from unittest.mock import Mock, patch

import pytest
from django.utils.encoding import smart_str

try:
    from mssql.base import CursorWrapper as MSSQLCursorWrapper
    from mssql.operations import DatabaseOperations as MSSQLDatabaseOperations

    from ansible_base.backends.mssql.base import DatabaseWrapper
    from ansible_base.backends.mssql.cursor_override import CursorWrapper
    from ansible_base.backends.mssql.schema import DatabaseSchemaEditor
except ModuleNotFoundError as exc:
    if exc.name != 'mssql':
        raise
    pytest.skip('mssql-django is required for SQL Server backend tests', allow_module_level=True)


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


def test_format_params_converts_uuids_before_delegating_to_parent():
    wrapper = make_cursor_wrapper(driver_charset='utf-8')
    value = uuid.uuid4()

    with patch.object(MSSQLCursorWrapper, 'format_params', return_value=('parent-formatted',)) as parent_format_params:
        assert wrapper.format_params(['hello', value, True]) == ('parent-formatted',)

    parent_format_params.assert_called_once_with(('hello', value.hex, True))


def test_database_wrapper_uses_mssql_operations_and_custom_schema_editor():
    assert DatabaseWrapper.SchemaEditorClass is DatabaseSchemaEditor
    assert issubclass(DatabaseWrapper.ops_class, MSSQLDatabaseOperations)
    assert DatabaseWrapper.ops_class.compiler_module == 'ansible_base.backends.mssql.compiler'
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
