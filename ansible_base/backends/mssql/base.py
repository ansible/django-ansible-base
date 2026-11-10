"""
Custom MS SQL Server database backend.

Extends mssql-django with a case-sensitive-collation compiler fix and
ISJSON check-constraint omission for encrypted JSONField values.
"""

import logging

from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper
from mssql.operations import DatabaseOperations as MSSQLDatabaseOperations

logger = logging.getLogger(__name__)

# The collation DAB is developed and tested against; a case-insensitive collation
# makes values differing only in case compare equal, breaking unique constraints
# and exact lookups. See docs/mssql-compatibility-guide.md.
REQUIRED_COLLATION = "Latin1_General_100_CS_AS"

# Database collation is fixed at CREATE DATABASE time and cannot drift within a
# process, so it is queried once per alias, on the first connection.
_collation_checked = set()


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

    def init_connection_state(self):
        # mssql-django leaves return_rows_bulk_insert off by default because OUTPUT
        # without INTO fails on tables with enabled triggers (mssql-django #130).
        # DAB's schema carries no triggers, and PostgreSQL (the reference backend)
        # populates bulk_create() primary keys, so default the option on here.
        # An explicit OPTIONS['return_rows_bulk_insert'] = False still opts out.
        self.settings_dict.setdefault('OPTIONS', {}).setdefault('return_rows_bulk_insert', True)
        super().init_connection_state()
        self._check_database_collation()

    def _check_database_collation(self):
        """
        Warn when a customer-provided database was not created with the tested collation.

        Local dev and test databases are provisioned with REQUIRED_COLLATION, but a
        bring-your-own database created elsewhere (installer, RDS, manual DBA setup)
        defaults to the server's case-insensitive collation. That silently changes
        equality semantics for every string comparison, so surface it at connect
        time rather than waiting for corrupted unique constraints.
        """
        if self.alias in _collation_checked:
            return
        _collation_checked.add(self.alias)
        cursor = self.create_cursor()
        cursor.execute("SELECT CONVERT(NVARCHAR(128), DATABASEPROPERTYEX(DB_NAME(), 'Collation'))")
        row = cursor.fetchone()
        if row is not None and row[0] != REQUIRED_COLLATION:
            logger.warning(
                "Database %r (alias %r) uses collation %s, but DAB requires %s; "
                "a case-insensitive collation makes values that differ only in case compare equal, "
                "breaking unique constraints and exact lookups. Recreate the database with "
                "CREATE DATABASE ... COLLATE %s before applying migrations.",
                self.settings_dict.get('NAME'),
                self.alias,
                row[0],
                REQUIRED_COLLATION,
                REQUIRED_COLLATION,
            )
