"""
Custom MS SQL Server database backend.

Extends mssql-django with automatic TextField-to-CharField conversion for
fields that have indexes or unique constraints.
"""

from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper

from .cursor_override import CursorWrapper
from .operations import DatabaseOperations
from .schema import DatabaseSchemaEditor


class DatabaseWrapper(MSSQLDatabaseWrapper):
    """
    Custom MS SQL database backend using our schema editor, operations, and cursor.

    This wrapper extends mssql-django's DatabaseWrapper to:
    - Use custom SchemaEditor for TextField-to-CharField conversion
    - Use custom DatabaseOperations for proper UUID handling
    - Use custom CursorWrapper to convert UUID parameters to strings
    - Remove ISJSON CHECK constraint from JSONFields

    Fixes:
    - TextField cannot be indexed on MS SQL Server (converts to CharField)
    - UUIDField causes OverflowError with pyodbc (converts to string via cursor wrapper)
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

    SchemaEditorClass = DatabaseSchemaEditor
    ops_class = DatabaseOperations

    # Override to remove ISJSON constraint from JSONField
    # This allows storing encrypted data in JSONField columns
    # (encrypted data is a string, not valid JSON, so would fail ISJSON check)
    data_type_check_constraints = {
        # 'JSONField': '(ISJSON ("%(column)s") = 1)',  # Removed - breaks encrypted JSONFields
        'PositiveIntegerField': '[%(column)s] >= 0',
        'PositiveSmallIntegerField': '[%(column)s] >= 0',
        'PositiveBigIntegerField': '[%(column)s] >= 0',
    }

    def create_cursor(self, name=None):
        """
        Create a cursor with UUID parameter handling.

        Overrides mssql-django's create_cursor to use our custom CursorWrapper
        that converts UUID objects to hex strings before passing to pyodbc.
        """
        return CursorWrapper(self.connection.cursor(), self)
