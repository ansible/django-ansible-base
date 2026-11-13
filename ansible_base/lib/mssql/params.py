"""SQL Server query-parameter accounting.

SQL Server caps a single query (really, an ``sp_executesql`` call) at 2100
parameters. A handful are consumed by the procedure machinery itself, so DAB
keeps a headroom margin below the hard ceiling.
"""

from collections.abc import Iterator, Sequence

from django.db import DEFAULT_DB_ALIAS, connections

# The hard ceiling documented by Microsoft for sp_executesql.
SQL_SERVER_MAX_QUERY_PARAMETERS = 2100

# Parameters reserved for the sp_executesql call itself (query text and
# parameter declarations); empirically it fails before reaching 2100.
SQL_SERVER_QUERY_PARAMETER_HEADROOM = 100


def in_chunks(values, *, params_per_value: int = 1, using: str | None = None) -> Iterator[Sequence]:
    """Yield ``values`` in chunks whose bound-parameter count stays under the SQL Server limit.

    Non-microsoft vendors get the whole input as a single chunk, so query
    behavior there is unchanged. ``params_per_value`` is the number of bound
    parameters each value contributes to the final statement — 2 for OR-pair
    ``Q`` filters, 3 for ``Case``/``When`` UPDATE entries. Empty input yields
    no chunks.

    Note: mssql-django already routes plain ``__in`` lookups through a
    ``#Temp_params`` table in batches, so ``in_chunks`` is only needed for
    constructs that bind every value inline — OR-ed ``Q`` pairs and
    ``Case`` expressions.
    """
    if not isinstance(values, Sequence):
        values = list(values)
    if not values:
        return
    using = using or DEFAULT_DB_ALIAS
    if connections[using].vendor != "microsoft":
        yield values
        return
    chunk_size = (SQL_SERVER_MAX_QUERY_PARAMETERS - SQL_SERVER_QUERY_PARAMETER_HEADROOM) // max(params_per_value, 1)
    for start in range(0, len(values), chunk_size):
        yield values[start : start + chunk_size]
