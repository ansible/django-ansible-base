"""
Override mssql-django's CursorWrapper to handle UUID parameters.

mssql-django's format_params() doesn't convert UUID objects to strings,
but SQL Server stores UUIDs as char(32) (not uniqueidentifier) when
has_native_uuid_field=False. We convert UUID objects to hex strings.
"""

import uuid

from mssql.base import CursorWrapper as MSSQLCursorWrapper


class CursorWrapper(MSSQLCursorWrapper):
    """
    Extended CursorWrapper that converts UUID objects to hex strings.

    Overrides format_params() to ensure UUID objects are converted to
    hex strings before being passed to pyodbc.
    """

    def format_params(self, params):
        """
        Format parameters for pyodbc, converting UUIDs to hex strings.

        Extends the parent implementation to handle UUID objects, which
        pyodbc doesn't support natively and would otherwise convert to
        128-bit integers (causing OverflowError).
        """
        if params is not None:
            params = tuple(param.hex if isinstance(param, uuid.UUID) else param for param in params)
        return super().format_params(params)
