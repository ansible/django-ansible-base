import pytest

try:
    import mssql.compiler as mssql_compiler

    from ansible_base.backends.mssql.compiler import SQLCompiler  # noqa: E402
except Exception as error:
    # mssql.compiler imports pyodbc, which needs the OS-level unixODBC libraries and the
    # Microsoft ODBC driver; a missing driver raises ImproperlyConfigured, which
    # importorskip does not catch. Skip instead of erroring at collection time.
    pytest.skip(f"MS SQL backend unavailable: {error}", allow_module_level=True)


def _compiler_with_canned_parent_sql(monkeypatch, canned_sql):
    """Build a SQLCompiler whose parent as_sql returns canned SQL, isolating the alias fix."""

    def fake_as_sql(self, with_limits=True, with_col_aliases=False):
        return canned_sql, []

    monkeypatch.setattr(mssql_compiler.SQLCompiler, 'as_sql', fake_as_sql)
    return SQLCompiler.__new__(SQLCompiler)


def test_as_sql_normalizes_col_aliases(monkeypatch):
    "Generated aliases must be lowercase to match Django's QUALIFY wrapper under CS collations."
    compiler = _compiler_with_canned_parent_sql(monkeypatch, 'SELECT [a] AS Col1, [b] AS Col2 FROM [t]')

    sql, params = compiler.as_sql(with_col_aliases=True)

    assert sql == 'SELECT [a] AS col1, [b] AS col2 FROM [t]'
    assert params == []


def test_as_sql_leaves_sql_alone_without_col_aliases(monkeypatch):
    "The rewrite only applies when Django asked for column aliases (sliced prefetch queries)."
    canned_sql = 'SELECT [a] AS Col1 FROM [t]'
    compiler = _compiler_with_canned_parent_sql(monkeypatch, canned_sql)

    sql, _ = compiler.as_sql(with_col_aliases=False)

    assert sql == canned_sql


def test_reexported_compilers_match_upstream():
    "The remaining compilers are re-exports; the backend only overrides the select compiler."
    import ansible_base.backends.mssql.compiler as dab_compiler

    assert dab_compiler.SQLAggregateCompiler is mssql_compiler.SQLAggregateCompiler
    assert dab_compiler.SQLDeleteCompiler is mssql_compiler.SQLDeleteCompiler
    assert dab_compiler.SQLInsertCompiler is mssql_compiler.SQLInsertCompiler
    assert dab_compiler.SQLUpdateCompiler is mssql_compiler.SQLUpdateCompiler
