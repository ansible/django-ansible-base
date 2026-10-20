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

from ansible_base.lib.dynamic_config import export, factory, load_envvars, load_standard_settings_files

# Create dynaconf instance with defaults (same as test_app.settings)
DYNACONF = factory(
    __name__,
    "TESTAPP",
    environments=("development", "sqlite"),
    settings_files=["defaults.py"],
)

# Load new standard settings files from /etc/ansible-automation-platform/
load_standard_settings_files(DYNACONF)

# Set overrides that must be set after DAB and file settings are loaded
DYNACONF.set(
    "ANSIBLE_BASE_JWT_MANAGED_ROLES",
    "@merge System Auditor",
    loader_identifier="add_system_auditor",
)

# Override DATABASES for MS SQL Server
# Must be set before export() to ensure migration selection works
DYNACONF.set(
    "DATABASES",
    {
        "default": {
            "ENGINE": "mssql",
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": int(os.getenv("DB_PORT", 55433)),
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
    },
    loader_identifier="mssql_override",
)

# Load envvars at the end to allow them to override everything loaded so far
load_envvars(DYNACONF)

# Update django.conf.settings with DYNACONF keys
# This will include OAUTH2_PROVIDER_APPLICATION_MODEL and other DAB defaults
export(__name__, DYNACONF)

# MS SQL Server doesn't need the PG_NOTIFY_DATABASES setting
# Consumer apps should use get_sql_server_notify_params() instead
# See ansible_base/lib/utils/db.py for dispatcherd Service Broker configuration
