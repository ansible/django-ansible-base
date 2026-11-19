from django.conf import settings
from django.db import DEFAULT_DB_ALIAS

from ansible_base.lib.utils.db import combine_settings_dict


def get_sql_server_notify_params(alias: str = DEFAULT_DB_ALIAS, **extra_options) -> dict:
    """
    Returns connection parameters for MS SQL Server Service Broker (dispatcherd sql_server broker).

    Similar to get_pg_notify_params() but for MS SQL Server. Consumer applications (Controller, Gateway,
    EDA) use these parameters to configure dispatcherd's sql_server broker to replace pg_notify.

    This uses the same connection parameters as Django's DATABASES configuration, with optional
    overrides specified by SQL_SERVER_NOTIFY_DATABASES setting (parallel to PG_NOTIFY_DATABASES).

    Args:
        alias: Django database alias (default: 'default')
        **extra_options: Additional connection options to merge (e.g. application_name)

    Returns:
        dict: pyodbc-compatible connection parameters for dispatcherd

    Example:
        # In consumer app (Controller, Gateway, EDA) dispatcherd configuration:
        from django.db import connection
        from ansible_base.lib.mssql.notify import get_sql_server_notify_params

        if connection.vendor == "microsoft":
            broker_config = {
                "sql_server": {
                    "config": get_sql_server_notify_params(),
                }
            }
    """
    sql_server_overrides = {}
    if hasattr(settings, "SQL_SERVER_NOTIFY_DATABASES"):
        sql_server_overrides = settings.SQL_SERVER_NOTIFY_DATABASES.get(alias, {})

    settings_dict = combine_settings_dict(settings.DATABASES[alias], sql_server_overrides, **extra_options)

    # Extract pyodbc connection parameters from Django settings
    params = {
        "server": settings_dict.get("HOST") or "localhost",
        "port": settings_dict.get("PORT") or 1433,
        "database": settings_dict.get("NAME"),
        "user": settings_dict.get("USER"),
        "password": settings_dict.get("PASSWORD"),
    }

    # Add OPTIONS if present (driver, extra_params, etc.)
    if "OPTIONS" in settings_dict:
        params.update(settings_dict["OPTIONS"])

    return params
