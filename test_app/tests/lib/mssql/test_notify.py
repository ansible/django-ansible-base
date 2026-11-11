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


def parse_odbc_connection_string(conn_string):
    """Minimal ODBC-style parser for round-trip assertions: splits on ';' outside
    braces, unwraps brace-quoted values, and un-doubles '}}'."""
    parts = []
    buf = ""
    in_braces = False
    i = 0
    while i < len(conn_string):
        char = conn_string[i]
        if in_braces:
            if char == "}":
                if i + 1 < len(conn_string) and conn_string[i + 1] == "}":
                    buf += "}"
                    i += 2
                    continue
                in_braces = False
            else:
                buf += char
        elif char == "{":
            in_braces = True
        elif char == ";":
            parts.append(buf)
            buf = ""
        else:
            buf += char
        i += 1
    parts.append(buf)
    return dict(part.split("=", 1) for part in parts if part)


def test_conn_string_escapes_special_characters():
    settings_dict = {
        "HOST": "db.example.com",
        "PORT": 55433,
        "NAME": "dab_db",
        "USER": "user;name",
        "PASSWORD": "p;={w}ord ",
        "OPTIONS": {"driver": "ODBC Driver 18 for SQL Server"},
    }
    conn_string = notify.sql_server_conn_string_from_settings_dict(settings_dict)

    parsed = parse_odbc_connection_string(conn_string)
    assert parsed["SERVER"] == "db.example.com,55433"
    assert parsed["DATABASE"] == "dab_db"
    assert parsed["UID"] == "user;name"
    assert parsed["PWD"] == "p;={w}ord "
    assert parsed["DRIVER"] == "ODBC Driver 18 for SQL Server"


def test_conn_string_translates_options():
    settings_dict = {
        "HOST": "db.example.com",
        "NAME": "dab_db",
        "OPTIONS": {
            "driver": "ODBC Driver 17 for SQL Server",
            "extra_params": "Encrypt=yes;TrustServerCertificate=yes",
            "MARS_Connection": "yes",
        },
    }
    conn_string = notify.sql_server_conn_string_from_settings_dict(settings_dict)

    assert "SERVER=db.example.com" in conn_string
    assert "DRIVER={ODBC Driver 17 for SQL Server}" in conn_string
    assert "MARS_Connection=yes" in conn_string
    assert conn_string.endswith("Encrypt=yes;TrustServerCertificate=yes")


def test_conn_string_named_instance_omits_port():
    settings_dict = {"HOST": r"db.example.com\INSTANCE", "NAME": "dab_db", "PORT": ""}
    conn_string = notify.sql_server_conn_string_from_settings_dict(settings_dict)

    assert "SERVER=db.example.com\\INSTANCE" in conn_string


def test_conn_string_applies_notify_database_overrides_and_extra_options():
    databases = {
        "default": {
            "ENGINE": "ansible_base.backends.mssql",
            "HOST": "database.example",
            "PORT": 1434,
            "NAME": "main",
            "USER": "user",
            "PASSWORD": "password",
            "OPTIONS": {"driver": "ODBC Driver 18 for SQL Server"},
        }
    }
    overrides = {"default": {"HOST": "listener.example", "OPTIONS": {"Encrypt": "yes"}}}
    with override_settings(DATABASES=databases, SQL_SERVER_NOTIFY_DATABASES=overrides):
        conn_string = notify.get_sql_server_notify_conn_string(application_name="dispatcherd")

    parsed = parse_odbc_connection_string(conn_string)
    assert parsed["SERVER"] == "listener.example,1434"
    assert parsed["DATABASE"] == "main"
    assert parsed["UID"] == "user"
    assert parsed["PWD"] == "password"
    assert parsed["Encrypt"] == "yes"
    assert parsed["application_name"] == "dispatcherd"


def test_conn_string_defaults_host_port_and_driver():
    databases = {"default": {"ENGINE": "ansible_base.backends.mssql", "NAME": "dab_db", "USER": "sa", "PASSWORD": "secret"}}
    with override_settings(DATABASES=databases):
        conn_string = notify.get_sql_server_notify_conn_string()

    parsed = parse_odbc_connection_string(conn_string)
    assert parsed["SERVER"] == "localhost,1433"
    assert parsed["DATABASE"] == "dab_db"
    assert parsed["UID"] == "sa"
    assert parsed["PWD"] == "secret"
    assert parsed["DRIVER"] == "ODBC Driver 18 for SQL Server"


def test_conn_string_agrees_with_get_sql_server_notify_params():
    with override_settings(DATABASES=MSSQL_DATABASE_DICT):
        params = notify.get_sql_server_notify_params()
        conn_string = notify.get_sql_server_notify_conn_string()

    parsed = parse_odbc_connection_string(conn_string)
    assert parsed["SERVER"] == f"{params['server']},{params['port']}"
    assert parsed["DATABASE"] == params["database"]
    assert parsed["UID"] == params["user"]
    assert parsed["PWD"] == params["password"]
