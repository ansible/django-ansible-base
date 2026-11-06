"""SQL compiler compatibility for case-sensitive SQL Server collations."""

import re

from mssql import compiler as mssql_compiler


class SQLCompiler(mssql_compiler.SQLCompiler):
    """Keep generated select aliases consistent with Django's qualify wrapper."""

    def as_sql(self, with_limits=True, with_col_aliases=False):
        sql, params = super().as_sql(with_limits=with_limits, with_col_aliases=with_col_aliases)
        if with_col_aliases:
            # Django references these aliases as ``col1``, while mssql-django
            # emits ``Col1``. They differ under the backend's case-sensitive
            # collation and break sliced prefetch queries that use QUALIFY.
            sql = re.sub(r'\bAS Col(\d+)\b', r'AS col\1', sql)
        return sql, params


SQLAggregateCompiler = mssql_compiler.SQLAggregateCompiler
SQLDeleteCompiler = mssql_compiler.SQLDeleteCompiler
SQLInsertCompiler = mssql_compiler.SQLInsertCompiler
SQLUpdateCompiler = mssql_compiler.SQLUpdateCompiler
