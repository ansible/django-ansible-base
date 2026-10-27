"""
Override mssql-django's CursorWrapper to handle UUID parameters.

mssql-django's format_params() doesn't convert UUID objects to strings,
but SQL Server stores UUIDs as char(32) (not uniqueidentifier) when
has_native_uuid_field=False. We convert UUID objects to hex strings.
"""

import uuid

from django.utils.encoding import smart_str
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
        if params is None:
            return ()
        return tuple(self._format_param(param) for param in params)

    def _format_param(self, param):
        """Normalize one parameter for pyodbc."""
        if isinstance(param, str):
            if self.driver_charset:
                # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                # yet, so we need to encode parameters in utf-8
                return smart_str(param, self.driver_charset)
            return param

        if isinstance(param, bytes):
            return param

        if isinstance(param, bool):
            return int(param)

        if isinstance(param, uuid.UUID):
            # SQL Server char(32) columns expect 32-character hexadecimal strings.
            return param.hex

        return param
