import pytest

try:
    from ansible_base.backends.mssql.base import DatabaseOperations, DatabaseWrapper  # noqa: E402
except Exception as error:
    # mssql.base imports pyodbc, which needs the OS-level unixODBC libraries and the
    # Microsoft ODBC driver; a missing driver raises ImproperlyConfigured, which
    # importorskip does not catch. Skip instead of erroring at collection time.
    pytest.skip(f"MS SQL backend unavailable: {error}", allow_module_level=True)


def test_compiler_module_routes_to_compat_compiler():
    assert DatabaseOperations.compiler_module == "ansible_base.backends.mssql.compiler"


def test_data_type_check_constraints_omit_isjson():
    "Encrypted JSONField values are ciphertext, not valid JSON; ISJSON would reject them."
    import mssql.base as upstream

    expected = {key: value for key, value in upstream.DatabaseWrapper.data_type_check_constraints.items() if key != "JSONField"}
    # the mapping is derived from mssql-django's, so new upstream constraints carry over
    assert DatabaseWrapper.data_type_check_constraints == expected
    assert "JSONField" not in DatabaseWrapper.data_type_check_constraints


def test_no_schema_editor_or_cursor_overrides():
    "The TextField-interception machinery from #1242 is intentionally not ported."
    import mssql.base as upstream

    assert DatabaseWrapper.SchemaEditorClass is upstream.DatabaseWrapper.SchemaEditorClass
    assert "create_cursor" not in DatabaseWrapper.__dict__
