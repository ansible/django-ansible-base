import logging
from unittest.mock import MagicMock

import pytest

try:
    from ansible_base.backends.mssql import base as mssql_base  # noqa: E402
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


def _wrapper_with_stubbed_init(monkeypatch, settings_dict, collation="Latin1_General_100_CS_AS"):
    """Build a DatabaseWrapper whose parent init_connection_state records the OPTIONS it sees
    and whose create_cursor reports the given database collation."""
    import mssql.base as upstream

    seen = {}
    monkeypatch.setattr(upstream.DatabaseWrapper, "init_connection_state", lambda self: seen.update(self.settings_dict["OPTIONS"]))
    wrapper = DatabaseWrapper(settings_dict, alias="default")
    cursor = MagicMock()
    cursor.fetchone.return_value = (collation,)
    monkeypatch.setattr(wrapper, "create_cursor", lambda: cursor)
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


def test_warns_on_unexpected_database_collation(monkeypatch, caplog):
    "A BYO database provisioned elsewhere can carry the wrong collation; warn once per alias."
    mssql_base._collation_warning_emitted.clear()
    wrapper, _ = _wrapper_with_stubbed_init(monkeypatch, {"OPTIONS": {}}, collation="SQL_Latin1_General_CP1_CI_AS")

    with caplog.at_level(logging.WARNING):
        wrapper.init_connection_state()

    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "SQL_Latin1_General_CP1_CI_AS" in warnings[0].getMessage()
    assert "Latin1_General_100_CS_AS" in warnings[0].getMessage()

    # the warning fires once per alias, not on every new connection
    wrapper.init_connection_state()
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1


def test_no_collation_warning_when_collation_matches(monkeypatch, caplog):
    mssql_base._collation_warning_emitted.clear()
    wrapper, _ = _wrapper_with_stubbed_init(monkeypatch, {"OPTIONS": {}})

    with caplog.at_level(logging.WARNING):
        wrapper.init_connection_state()

    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
