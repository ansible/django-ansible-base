"""
Custom database operations for MS SQL Server.

Provides compatibility for database features not supported in MS SQL Server.
"""

from mssql.operations import DatabaseOperations as MSSQLDatabaseOperations


class DatabaseOperations(MSSQLDatabaseOperations):
    """
    Custom database operations for MS SQL Server backend.

    Currently uses default mssql-django operations.
    """

    pass
