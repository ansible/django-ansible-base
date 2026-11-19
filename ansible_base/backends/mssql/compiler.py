"""SQL compiler compatibility for case-sensitive SQL Server collations."""

from mssql import compiler as mssql_compiler


class SQLCompiler(mssql_compiler.SQLCompiler):
    """
    Forward ``with_col_aliases`` to ``pre_sql_setup()`` the way Django's own
    ``SQLCompiler.as_sql()`` does.

    mssql-django calls ``pre_sql_setup()`` with no arguments, so ``self.select``
    has no aliases and its ``as_sql()`` makes up ``Col1``, ``Col2``, ...
    Django's ``get_qualify_sql()`` refers to those columns as ``col1``, ...,
    and the two names differ under a case-sensitive collation.
    """

    _with_col_aliases = False

    def as_sql(self, with_limits=True, with_col_aliases=False):
        self._with_col_aliases = with_col_aliases or bool(self.query.combinator)
        return super().as_sql(with_limits=with_limits, with_col_aliases=with_col_aliases)

    def pre_sql_setup(self, with_col_aliases=False):
        return super().pre_sql_setup(with_col_aliases=with_col_aliases or self._with_col_aliases)


SQLAggregateCompiler = mssql_compiler.SQLAggregateCompiler
SQLDeleteCompiler = mssql_compiler.SQLDeleteCompiler
SQLInsertCompiler = mssql_compiler.SQLInsertCompiler
SQLUpdateCompiler = mssql_compiler.SQLUpdateCompiler
