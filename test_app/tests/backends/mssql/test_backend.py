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


def _wrapper_with_stubbed_init(monkeypatch, settings_dict):
    """Build a DatabaseWrapper whose parent init_connection_state records the OPTIONS it sees."""
    import mssql.base as upstream

    seen = {}
    monkeypatch.setattr(upstream.DatabaseWrapper, "init_connection_state", lambda self: seen.update(self.settings_dict["OPTIONS"]))
    wrapper = DatabaseWrapper(settings_dict, alias="default")
    return wrapper, seen


def test_return_rows_bulk_insert_defaults_on(monkeypatch):
    "bulk_create() populates PKs on PostgreSQL; the backend defaults SQL Server to the same behavior."
    wrapper, seen = _wrapper_with_stubbed_init(monkeypatch, {"OPTIONS": {}})

    wrapper.init_connection_state()

    assert seen["return_rows_bulk_insert"] is True


def test_return_rows_bulk_insert_explicit_opt_out(monkeypatch):
    "A deployment with triggers on managed tables can still turn the option off."
    wrapper, seen = _wrapper_with_stubbed_init(monkeypatch, {"OPTIONS": {"return_rows_bulk_insert": False}})

    wrapper.init_connection_state()

    assert seen["return_rows_bulk_insert"] is False
