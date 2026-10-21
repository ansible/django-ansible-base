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
