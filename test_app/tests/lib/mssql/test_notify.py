from django.test import override_settings

from ansible_base.lib.mssql import notify

MSSQL_DATABASE_DICT = {
    "default": {
        "ENGINE": "ansible_base.backends.mssql",
        "HOST": "db.example.com",
        "PORT": 1433,
        "USER": "sa",
        "PASSWORD": "secret",
        "NAME": "dab_db",
        "OPTIONS": {"driver": "ODBC Driver 18 for SQL Server"},
    }
}


def test_default_behavior():
    with override_settings(DATABASES=MSSQL_DATABASE_DICT):
        params = notify.get_sql_server_notify_params()

    assert params == {
        "server": "db.example.com",
        "port": 1433,
        "database": "dab_db",
        "user": "sa",
        "password": "secret",
        "driver": "ODBC Driver 18 for SQL Server",
    }


def test_get_sql_server_notify_params_applies_overrides_and_options():
    databases = {
        "default": {
            "ENGINE": "ansible_base.backends.mssql",
            "HOST": "database.example",
            "PORT": 1434,
            "NAME": "main",
            "USER": "user",
            "PASSWORD": "password",
            "OPTIONS": {"driver": "ODBC Driver"},
        }
    }
    overrides = {"default": {"HOST": "listener.example", "OPTIONS": {"Encrypt": "yes"}}}
    with override_settings(DATABASES=databases, SQL_SERVER_NOTIFY_DATABASES=overrides):
        params = notify.get_sql_server_notify_params(application_name="dispatcherd")

    assert params == {
        "server": "listener.example",
        "port": 1434,
        "database": "main",
        "user": "user",
        "password": "password",
        "driver": "ODBC Driver",
        "application_name": "dispatcherd",
        "Encrypt": "yes",
    }


def test_get_sql_server_notify_params_uses_host_and_port_defaults(monkeypatch):
    databases = {"replica": {"ENGINE": "ansible_base.backends.mssql", "NAME": "replica_db"}}
    monkeypatch.setattr(
        notify,
        "combine_settings_dict",
        lambda *args, **kwargs: {"HOST": "", "PORT": "", "NAME": "replica_db"},
    )
    with override_settings(DATABASES=databases):
        params = notify.get_sql_server_notify_params(alias="replica")

    assert params == {
        "server": "localhost",
        "port": 1433,
        "database": "replica_db",
        "user": None,
        "password": None,
    }
