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

    # Inherit mssql-django's check constraints, dropping only JSONField's ISJSON:
    # DAB stores encrypted (non-JSON) ciphertext in JSONField columns, which ISJSON rejects.
    # Deriving from the upstream mapping keeps any constraints mssql-django adds in
    # future versions instead of pinning a copy of the current ones.
    data_type_check_constraints = {key: value for key, value in MSSQLDatabaseWrapper.data_type_check_constraints.items() if key != 'JSONField'}
