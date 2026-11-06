"""
Custom MS SQL Server database backend.

Extends mssql-django with a case-sensitive-collation compiler fix and
ISJSON check-constraint omission for encrypted JSONField values.
"""

from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper
from mssql.operations import DatabaseOperations as MSSQLDatabaseOperations


class DatabaseOperations(MSSQLDatabaseOperations):
    """Route Django query compilation through the case-sensitive alias fix."""

    compiler_module = 'ansible_base.backends.mssql.compiler'


class DatabaseWrapper(MSSQLDatabaseWrapper):
    """
    Custom MS SQL database backend using our operations class.

    This wrapper extends mssql-django's DatabaseWrapper to:
    - Use a compiler that keeps select aliases consistent under case-sensitive collations
    - Remove ISJSON CHECK constraint from JSONFields

    Fixes:
    - Sliced prefetch queries break under case-sensitive collations (compiler alias normalization)
    - Encrypted JSON data fails ISJSON validation (removes constraint)

    Usage in settings.py:
        DATABASES = {
            'default': {
                'ENGINE': 'ansible_base.backends.mssql',
                'NAME': 'your_database',
                # ... other settings
            }
        }
    """

    ops_class = DatabaseOperations

    # Override to remove ISJSON constraint from JSONField
    # This allows storing encrypted data in JSONField columns
    # (encrypted data is a string, not valid JSON, so would fail ISJSON check)
    positive_field_constraint = '[%(column)s] >= 0'
    data_type_check_constraints = {
        # 'JSONField': '(ISJSON ("%(column)s") = 1)',  # Removed - breaks encrypted JSONFields
        'PositiveIntegerField': positive_field_constraint,
        'PositiveSmallIntegerField': positive_field_constraint,
        'PositiveBigIntegerField': positive_field_constraint,
    }
