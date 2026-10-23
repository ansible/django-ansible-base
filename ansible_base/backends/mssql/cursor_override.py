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
        fp = []
        if params is not None:
            for p in params:
                if isinstance(p, str):
                    if self.driver_charset:
                        # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                        # yet, so we need to encode parameters in utf-8
                        fp.append(smart_str(p, self.driver_charset))
                    else:
                        fp.append(p)

                elif isinstance(p, bytes):
                    fp.append(p)

                elif isinstance(p, type(True)):
                    if p:
                        fp.append(1)
                    else:
                        fp.append(0)

                elif isinstance(p, uuid.UUID):
                    # Convert UUID to hex string for pyodbc binding
                    # SQL Server char(32) column expects 32-character hex string
                    fp.append(p.hex)

                else:
                    fp.append(p)

        return tuple(fp)
