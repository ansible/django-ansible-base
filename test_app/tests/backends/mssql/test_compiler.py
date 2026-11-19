from types import SimpleNamespace
from unittest import skipUnless

import pytest
from django.db import connection
from django.db.models import Window
from django.db.models.functions import RowNumber
from django.test import TestCase

from test_app.models import ExampleEvent

try:
    import mssql.compiler as mssql_compiler

    from ansible_base.backends.mssql.compiler import SQLCompiler  # noqa: E402
except Exception as error:
    # mssql.compiler imports pyodbc, which needs the OS-level unixODBC libraries and the
    # Microsoft ODBC driver; a missing driver raises ImproperlyConfigured, which
    # importorskip does not catch. Skip instead of erroring at collection time.
    pytest.skip(f"MS SQL backend unavailable: {error}", allow_module_level=True)


class _Aborted(Exception):
    """Raised by tests to stop upstream as_sql() right after the call under observation."""


class _FakeQuery:
    """The query attributes mssql-django's as_sql() touches around pre_sql_setup()."""

    combinator = None
    alias_refcount = {}

    def reset_refcounts(self, refcounts):
        pass


def test_upstream_as_sql_calls_pre_sql_setup_without_arguments(monkeypatch):
    """The alias fix forwards with_col_aliases via pre_sql_setup, which only works while
    upstream as_sql() calls self.pre_sql_setup() with no arguments (Django forwards it,
    mssql-django does not). If upstream starts forwarding, this test fails and the
    override can be simplified."""
    recorded = {}

    def recording_pre_sql_setup(self, with_col_aliases=False):
        recorded["with_col_aliases"] = with_col_aliases
        raise _Aborted

    # patch our class so the recording replaces our own forwarding override and
    # observes the argument upstream as_sql() actually passes
    monkeypatch.setattr(SQLCompiler, "pre_sql_setup", recording_pre_sql_setup)
    compiler = SQLCompiler.__new__(SQLCompiler)
    compiler.query = _FakeQuery()

    with pytest.raises(_Aborted):
        compiler.as_sql(with_col_aliases=True)

    assert recorded["with_col_aliases"] is False


def test_as_sql_stores_col_alias_flag(monkeypatch):
    "as_sql records the flag so the argless pre_sql_setup() call can recover it."

    def fake_as_sql(self, with_limits=True, with_col_aliases=False):
        return "SELECT 1", []

    monkeypatch.setattr(mssql_compiler.SQLCompiler, "as_sql", fake_as_sql)
    compiler = SQLCompiler.__new__(SQLCompiler)
    compiler.query = SimpleNamespace(combinator=None)

    compiler.as_sql(with_col_aliases=True)
    assert compiler._with_col_aliases is True

    compiler.as_sql(with_col_aliases=False)
    assert compiler._with_col_aliases is False

    # Django aliases combinator queries unconditionally; mirror that.
    compiler.query = SimpleNamespace(combinator="union")
    compiler.as_sql(with_col_aliases=False)
    assert compiler._with_col_aliases is True


def test_pre_sql_setup_injects_stored_col_alias_flag(monkeypatch):
    "pre_sql_setup forwards the stored flag to Django's implementation."
    recorded = {}

    def fake_pre_sql_setup(self, with_col_aliases=False):
        recorded["with_col_aliases"] = with_col_aliases
        return [], None, None

    monkeypatch.setattr(mssql_compiler.SQLCompiler, "pre_sql_setup", fake_pre_sql_setup)
    compiler = SQLCompiler.__new__(SQLCompiler)
    compiler._with_col_aliases = True

    compiler.pre_sql_setup()

    assert recorded["with_col_aliases"] is True


def test_pre_sql_setup_passes_explicit_flag_through(monkeypatch):
    "An explicit with_col_aliases argument wins over the stored flag."
    recorded = {}

    def fake_pre_sql_setup(self, with_col_aliases=False):
        recorded["with_col_aliases"] = with_col_aliases
        return [], None, None

    monkeypatch.setattr(mssql_compiler.SQLCompiler, "pre_sql_setup", fake_pre_sql_setup)
    compiler = SQLCompiler.__new__(SQLCompiler)
    compiler._with_col_aliases = False

    compiler.pre_sql_setup(with_col_aliases=True)

    assert recorded["with_col_aliases"] is True


def test_reexported_compilers_match_upstream():
    "The remaining compilers are re-exports; the backend only overrides the select compiler."
    import ansible_base.backends.mssql.compiler as dab_compiler

    assert dab_compiler.SQLAggregateCompiler is mssql_compiler.SQLAggregateCompiler
    assert dab_compiler.SQLDeleteCompiler is mssql_compiler.SQLDeleteCompiler
    assert dab_compiler.SQLInsertCompiler is mssql_compiler.SQLInsertCompiler
    assert dab_compiler.SQLUpdateCompiler is mssql_compiler.SQLUpdateCompiler


@skipUnless(connection.vendor == "microsoft", "MS SQL Server only")
class QualifyQueryTests(TestCase):
    """Filtering on a window annotation routes through Django's QUALIFY wrapper, whose
    outer query references the inner select aliases as lowercase col1, col2, ... —
    while an unpatched mssql-django emits uppercase Col1. Under the case-sensitive
    collation this is an 'Invalid column name' error."""

    def test_filter_on_window_annotation(self):
        events = [ExampleEvent.objects.create(name=f"event {i}") for i in range(5)]

        ranked = list(ExampleEvent.objects.annotate(row_number=Window(RowNumber(), order_by="pk")).filter(row_number__lte=3))

        assert [event.pk for event in ranked] == [event.pk for event in events[:3]]
