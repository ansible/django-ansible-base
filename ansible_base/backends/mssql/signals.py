"""
Django signals to configure MS SQL Server connection for UUID handling.

Uses connection_created signal to set up proper UUID parameter conversion.
"""

import uuid

from django.db.backends.signals import connection_created
from django.dispatch import receiver

SQL_GUID = -11


def _guid_to_uuid(value):
    """Convert a SQL Server uniqueidentifier result to a Python UUID."""
    if value is None or isinstance(value, uuid.UUID):
        return value
    if isinstance(value, bytes):
        return uuid.UUID(bytes_le=value)
    if isinstance(value, str):
        return uuid.UUID(value)
    return value


@receiver(connection_created)
def setup_uuid_handling(sender, connection, **kwargs):
    """
    Configure pyodbc to handle UUID parameters correctly.

    pyodbc doesn't natively handle Python UUID objects and may try to convert
    them to integers, causing OverflowError. This sets up converters to handle
    UUIDs as strings.
    """
    if connection.vendor != 'microsoft':
        return

    raw_conn = connection.connection
    if raw_conn is None or not hasattr(raw_conn, 'add_output_converter'):
        return

    raw_conn.add_output_converter(SQL_GUID, _guid_to_uuid)
