"""
Custom MS SQL Server database backend.

Extends mssql-django with automatic TextField-to-CharField conversion for
fields that have indexes or unique constraints.
"""

from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper

from .schema import DatabaseSchemaEditor


class DatabaseWrapper(MSSQLDatabaseWrapper):
    """
    Custom MS SQL database backend using our schema editor.

    This wrapper extends mssql-django's DatabaseWrapper to use our custom
    SchemaEditor that handles TextField-to-CharField conversion automatically
    during migration execution.

    Also removes ISJSON CHECK constraint from JSONFields to support encrypted
    JSON data (which is stored as a string and fails JSON validation).

    Usage in settings.py:
        DATABASES = {
            'default': {
                'ENGINE': 'ansible_base.backends.mssql',
                'NAME': 'your_database',
                # ... other settings
            }
        }
    """

    SchemaEditorClass = DatabaseSchemaEditor

    # Override to remove ISJSON constraint from JSONField
    # This allows storing encrypted data in JSONField columns
    # (encrypted data is a string, not valid JSON, so would fail ISJSON check)
    data_type_check_constraints = {
        # 'JSONField': '(ISJSON ("%(column)s") = 1)',  # Removed - breaks encrypted JSONFields
        'PositiveIntegerField': '[%(column)s] >= 0',
        'PositiveSmallIntegerField': '[%(column)s] >= 0',
        'PositiveBigIntegerField': '[%(column)s] >= 0',
    }
