"""
Validators for MS SQL Server compatibility.

These validators only enforce constraints when using MS SQL Server as the database backend.
PostgreSQL and other databases are unaffected.

These validators are designed to be serializable by Django's migration system.
"""

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class MSSQLTextLengthValidator:
    """
    Validator for TextField length on MS SQL Server.

    Only enforces the max_length limit when using MS SQL Server as the database backend.
    PostgreSQL and other databases are unaffected.

    Marked with @deconstructible so Django migrations can serialize it.
    """

    message = _(
        'This field is limited to %(max_length)d characters when using MS SQL Server. '
        'Current length: %(current_length)d characters.'
    )
    code = 'mssql_max_length'

    def __init__(self, max_length):
        """
        Initialize the validator.

        Args:
            max_length: Maximum allowed length when using MS SQL Server
        """
        self.max_length = max_length

    def __call__(self, value):
        """
        Validate the value.

        Args:
            value: The field value to validate

        Raises:
            ValidationError: If using MS SQL Server and value exceeds max_length
        """
        if not value:
            return

        # Only enforce on MS SQL Server
        if connection.vendor == 'microsoft' and len(value) > self.max_length:
            raise ValidationError(
                self.message,
                code=self.code,
                params={'max_length': self.max_length, 'current_length': len(value)},
            )

    def __eq__(self, other):
        """Support comparison for Django migration optimization."""
        return isinstance(other, self.__class__) and self.max_length == other.max_length


# Pre-configured validators for common field types
validate_mssql_description = MSSQLTextLengthValidator(4000)
"""Validator for description fields (4000 char limit on MS SQL)."""

validate_mssql_object_id = MSSQLTextLengthValidator(450)
"""Validator for object_id fields (450 char limit on MS SQL for indexing)."""

validate_mssql_codename = MSSQLTextLengthValidator(100)
"""Validator for codename fields (100 char Django standard)."""
