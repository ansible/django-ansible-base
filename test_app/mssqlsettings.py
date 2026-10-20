"""
MS SQL Server settings for test_app.
Loaded when DB_BACKEND=mssql environment variable is set.

WARNING: This configuration is for DEVELOPMENT AND TESTING ONLY.
TrustServerCertificate=yes bypasses certificate verification and is NOT
suitable for production use. Production deployments must use proper
TLS/SSL certificate validation per ANSTRAT-1887 R3.

Usage:
    DB_BACKEND=mssql python manage.py runserver
    DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh

Part of ANSTRAT-1887: MS SQL Server Database Support - Technology Preview
"""
import os

# Inherit from defaults
from test_app.defaults import *  # noqa: F403, F401

# Override database configuration for MS SQL Server
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", 55433),
        "USER": os.getenv("DB_USER", "sa"),
        "PASSWORD": os.getenv("DB_PASSWORD", "YourStrong!Passw0rd"),
        "NAME": os.getenv("DB_NAME", "dab_db"),
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            # WARNING: TrustServerCertificate=yes is for DEVELOPMENT ONLY
            # Production must use proper certificate validation
            # See ANSTRAT-1887 R3 for production TLS/SSL requirements
            "extra_params": "TrustServerCertificate=yes",
        },
    }
}

# MS SQL Server doesn't need the PG_NOTIFY_DATABASES setting
# Consumer apps should use get_sql_server_notify_params() instead
# See ansible_base/lib/utils/db.py for dispatcherd Service Broker configuration
