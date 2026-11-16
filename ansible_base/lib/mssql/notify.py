from django.conf import settings
from django.db import DEFAULT_DB_ALIAS

from ansible_base.lib.utils.db import combine_settings_dict

DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"

_ODBC_SPECIAL_CHARACTERS = (";", "=", "{", "}")


def _odbc_escape(value, always: bool = False) -> str:
    """Escape a value for an ODBC connection string keyword.

    Values containing ``;``, ``=``, ``{``, ``}`` or leading/trailing whitespace
    are wrapped in braces, with inner braces doubled.
    """
    text = str(value)
    needs_braces = always or any(char in text for char in _ODBC_SPECIAL_CHARACTERS) or text != text.strip()
    if needs_braces:
        return "{" + text.replace("}", "}}") + "}"
    return text


def sql_server_conn_string_from_settings_dict(settings_dict: dict) -> str:
    """Render an ODBC connection string from a Django DATABASES settings dict.

    Intended for consumers like the dispatcherd sql_server broker, whose
    ``connect`` takes a pre-rendered ``connection_string`` (everything else in
    its config is passed as pyodbc.connect kwargs). Translation:

    - ``HOST`` (plus ```,PORT`` when a numeric port is set and the host is not
      a named instance) → ``SERVER``
    - ``NAME`` → ``DATABASE``, ``USER`` → ``UID``, ``PASSWORD`` → ``PWD``
    - ``OPTIONS['driver']`` → ``DRIVER`` (default ODBC Driver 18 for SQL Server)
    - ``OPTIONS['extra_params']`` is appended verbatim
    - remaining ``OPTIONS`` keys pass through as ``KEYWORD=value``
    """
    options = settings_dict.get("OPTIONS") or {}
    parts = []

    host = settings_dict.get("HOST")
    if host:
        server = str(host)
        port = settings_dict.get("PORT")
        # a named instance (host\\instance) takes the port slot; both cannot be given
        if "\\" not in server and port:
            server = f"{server},{port}"
        parts.append(f"SERVER={_odbc_escape(server)}")
    if settings_dict.get("NAME"):
        parts.append(f"DATABASE={_odbc_escape(settings_dict['NAME'])}")
    if settings_dict.get("USER"):
        parts.append(f"UID={_odbc_escape(settings_dict['USER'])}")
    if settings_dict.get("PASSWORD"):
        parts.append(f"PWD={_odbc_escape(settings_dict['PASSWORD'])}")

    # DRIVER values conventionally carry spaces, so they are always braced
    parts.append(f"DRIVER={_odbc_escape(options.get('driver', DEFAULT_ODBC_DRIVER), always=True)}")

    for key, value in options.items():
        if key in ("driver", "extra_params"):
            continue
        parts.append(f"{key}={_odbc_escape(value)}")

    extra_params = options.get("extra_params")
    if extra_params:
        parts.append(str(extra_params))

    return ";".join(parts)


def get_sql_server_notify_conn_string(alias: str = DEFAULT_DB_ALIAS, **extra_options) -> str:
    """Returns an ODBC connection string for the dispatcherd SQL Server broker.

    dispatcherd's ``sql_server`` broker pops a pre-rendered ``connection_string``
    from its config and passes everything else to ``pyodbc.connect`` as kwargs,
    so server/database/credentials have to travel inside the string. This is the
    MS SQL Server counterpart of :func:`ansible_base.lib.utils.db.get_pg_notify_params`:
    it starts from Django's ``DATABASES[alias]``, applies optional overrides from
    the ``SQL_SERVER_NOTIFY_DATABASES`` setting (parallel to ``PG_NOTIFY_DATABASES``)
    and any ``**extra_options`` (e.g. ``application_name``), then renders the
    merged settings via :func:`sql_server_conn_string_from_settings_dict`.
    Default host, port, and driver are localhost, 1433, and ODBC Driver 18.

    Example:
        # In consumer app (Controller, Gateway, EDA) dispatcherd configuration:
        from django.db import connection
        from ansible_base.lib.mssql.notify import get_sql_server_notify_conn_string

        if connection.vendor == "microsoft":
            broker_config = {
                "sql_server": {
                    "config": {"connection_string": get_sql_server_notify_conn_string()},
                }
            }
    """
    sql_server_overrides = {}
    if hasattr(settings, "SQL_SERVER_NOTIFY_DATABASES"):
        sql_server_overrides = settings.SQL_SERVER_NOTIFY_DATABASES.get(alias, {})

    settings_dict = combine_settings_dict(settings.DATABASES[alias], sql_server_overrides, **extra_options)
    if not settings_dict.get("HOST"):
        settings_dict["HOST"] = "localhost"
    if not settings_dict.get("PORT"):
        settings_dict["PORT"] = 1433

    return sql_server_conn_string_from_settings_dict(settings_dict)
