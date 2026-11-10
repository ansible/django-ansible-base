"""SQL Server query-parameter accounting.

SQL Server caps a single query (really, an ``sp_executesql`` call) at 2100
parameters. A handful are consumed by the procedure machinery itself, so DAB
keeps a headroom margin below the hard ceiling.
"""

# The hard ceiling documented by Microsoft for sp_executesql.
SQL_SERVER_MAX_QUERY_PARAMETERS = 2100

# Parameters reserved for the sp_executesql call itself (query text and
# parameter declarations); empirically it fails before reaching 2100.
SQL_SERVER_QUERY_PARAMETER_HEADROOM = 100
