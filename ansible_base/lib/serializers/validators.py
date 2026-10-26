"""
Serializer validators for database-specific constraints.

Provides clean API validation errors for database-specific limitations
without requiring model-level validators or migrations.
"""

from django.core.exceptions import ValidationError
from django.db import connection


def validate_mssql_text_length(value, max_length, field_name='This field'):
    """
    Validate TextField length for MS SQL Server compatibility.

    SQL Server converts indexed/unique TextFields to CharField with a max_length
    during schema creation. This validator provides clean API errors before
    data hits the database.

    Args:
        value: The field value to validate
        max_length: Maximum length allowed on SQL Server
        field_name: Human-readable field name for error messages

    Raises:
        ValidationError: When value exceeds max_length on SQL Server

    Usage in serializers:
        from ansible_base.lib.serializers.validators import validate_mssql_text_length

        def validate_description(self, value):
            validate_mssql_text_length(value, max_length=4000, field_name='Description')
            return value
    """
    if not value:
        return

    # Only enforce on SQL Server
    if connection.vendor != 'microsoft':
        return

    if len(value) > max_length:
        raise ValidationError(
            f"{field_name} is limited to {max_length} characters when using MS SQL Server. "
            f"Current length: {len(value)} characters."
        )


# Convenience validators for common field types
def validate_mssql_description(value):
    """Validate description field (4000 char limit on SQL Server)."""
    validate_mssql_text_length(value, max_length=4000, field_name='Description')


def validate_mssql_object_id(value):
    """Validate object_id field (450 char limit on SQL Server)."""
    validate_mssql_text_length(value, max_length=450, field_name='Object ID')


def validate_mssql_codename(value):
    """Validate codename field (100 char limit on SQL Server)."""
    validate_mssql_text_length(value, max_length=100, field_name='Codename')
