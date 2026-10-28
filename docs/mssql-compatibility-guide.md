# SQL Server compatibility and migration guide

django-ansible-base includes a SQL Server backend built on `mssql-django`. This guide covers the setup decisions and schema behavior to review when deploying an application that uses DAB with SQL Server.

## Python dependencies and ODBC driver

The Python runtime requirements in [`requirements/requirements.in`](../requirements/requirements.in) include `mssql-django` and `pyodbc` as base dependencies. They are installed for all DAB consumers; there is no separate MSSQL extra to enable.

The Microsoft ODBC Driver is an operating-system dependency and is not installed by pip. Install Microsoft ODBC Driver 18 in the application image or host, and configure the Django driver name as `ODBC Driver 18 for SQL Server`. Use Microsoft's current [Linux installation guide](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server) or [Windows download page](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) for the packages matching your platform. Linux builds that compile `pyodbc` may also need the distribution's `unixODBC` development headers.

Configure the database with DAB's backend engine:

```python
DATABASES = {
    "default": {
        "ENGINE": "ansible_base.backends.mssql",
        "NAME": "app_db",
        "HOST": "sql.example.com",
        "PORT": 1433,
        "USER": "app_user",
        "PASSWORD": "...",
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
        },
    },
}
```

ODBC Driver 18 requires an appropriate TLS configuration. Production deployments should validate the SQL Server certificate; the test settings' `TrustServerCertificate=yes` option is for development only.

## Database collation

Create every database used by a DAB application with the case and accent sensitive collation `Latin1_General_100_CS_AS` before applying migrations:

```sql
CREATE DATABASE [app_db] COLLATE Latin1_General_100_CS_AS;
```

The collation determines equality and ordering for strings. SQL Server's default case-insensitive collation can make values that differ only by case compare equal, affecting unique constraints and exact lookups. `CS_AS` makes those comparisons case-sensitive and accent-sensitive, matching the intended PostgreSQL behavior more closely.

Set the collation on each application database explicitly; a server-level default does not replace this provisioning requirement. Changing a database's default collation does not update the collation of existing string columns. For an existing database, plan and test a migration of the affected columns and indexes rather than relying on `ALTER DATABASE ... COLLATE` alone.

Use the tested `Latin1_General_100_CS_AS` name as written. Do not add `_SC` or `_UTF8` with the current DAB SQL Server schema: SQL Server rejects the legacy `text`/`ntext` operations used by this stack with those collation flags.

## `TextField` schema conversion and length limits

SQL Server maps an unconstrained Django `TextField` to `nvarchar(max)`, which cannot be used as an index or unique key. DAB's schema editor automatically narrows a `TextField` when it has `db_index=True` or `unique=True`, or participates in `unique_together`, a `UniqueConstraint`, or a model index. The migration files do not need to change for this conversion.

The schema editor selects the `nvarchar(n)` length from the field name:

| Field name rule | SQL Server column length |
| --- | ---: |
| Contains `codename` | 100 |
| Contains `object_id` or `parent_reference` | 450 |
| Exactly `name` | 255 |
| Contains `singleton` or `role_field` | 64 |
| Any other constrained `TextField` | 450 |

Unconstrained `TextField`s remain `nvarchar(max)`. These limits apply to the columns narrowed for indexing; they are not a blanket limit on every text field. If an existing `nvarchar(max)` column is later indexed or constrained, the schema editor alters it to the selected length before creating the index or constraint. That operation does not truncate data: it will fail if existing values exceed the new column length.

Before adding an index or unique constraint to an existing `TextField`, inspect its data and resolve overlength values. DAB's `CommonModelSerializer` applies the same schema-derived maximum to constrained `TextField` API fields on SQL Server. Custom serializers that don't use it can call `ansible_base.lib.serializers.validators.validate_mssql_text_length()` or the convenience validators `validate_mssql_object_id()`, `validate_mssql_parent_reference()`, and `validate_mssql_codename()`. These validators are conditional on the active database being SQL Server. DAB also keeps an explicit 4,000-character API policy for descriptions in selected RBAC and OAuth serializers; descriptions remain `nvarchar(max)` unless constrained separately.

## Other backend behavior

- SQL Server stores `JSONField` values as `nvarchar(max)`. DAB omits the `ISJSON` check constraint so encrypted JSON values can be stored.
- The REST filter backend rejects `__regex` and `__iregex` with HTTP 400 on SQL Server because the backend's `dbo.REGEXP_LIKE` function is not installed by default. See [REST filter lookups](apps/rest_filters.md#regex-lookups).
- DAB's `advisory_lock()` uses SQL Server's `sp_getapplock`; see the [advisory lock guide](lib/advisory_lock.md).

## Testing

The repository's SQL Server test environment creates its database with `Latin1_General_100_CS_AS`. To run the full test suite against SQL Server, use `tox -e py312-mssql`; for PostgreSQL use `tox -e py312`. See [testing instructions](testing.md) for the test database setup.
