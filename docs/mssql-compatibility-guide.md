# SQL Server compatibility and migration guide

django-ansible-base supports Microsoft SQL Server through the `ansible_base.backends.mssql` database engine, built on [mssql-django](https://github.com/microsoft/mssql-django). PostgreSQL remains the reference backend: every feature is developed and tested against PostgreSQL first, and the SQL Server support exists so that AAP components can run on either database. This guide covers the dependencies, collation, field, and backend behavior to review when deploying an application that uses DAB with SQL Server.

**Current status:** the backend, its DDL, and the development environment are complete — every Django migration applies cleanly on SQL Server. The remaining gap is bulk-write data paths (tracked under AAP-98732): a first `manage.py migrate` exits non-zero *after* applying all migrations, because the `resource_registry` post-migrate backfill uses `bulk_create(ignore_conflicts=True)`, which mssql-django does not support (a second run succeeds with nothing to apply). Until the follow-up work lands, `DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh` stops at that migrate step and the `py312-mssql` tox suite is not green.

## Python dependencies and ODBC driver

The SQL Server Python dependencies are in the optional `mssql` extra. Install them with `pip install 'django-ansible-base[mssql]'` (or include `mssql` alongside the other extras your application uses). The `all` extra includes the SQL Server dependencies.

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

The backend checks the collation when it first connects and logs a warning if the database does not use `Latin1_General_100_CS_AS` (once per process per database alias). The warning is advisory: provision the database correctly rather than relying on the check, and treat a warning as a sign that equality semantics differ from what DAB is tested with.

## `BoundedTextField` for indexed text columns

SQL Server maps an unconstrained Django `TextField` to `nvarchar(max)`, which cannot be used as an index or unique key. DAB's answer is the `BoundedTextField` model field: a `TextField` that declares a `sql_server_max_length`, becomes `nvarchar(N)` on SQL Server, and behaves exactly like a plain `TextField` on PostgreSQL. There is no schema-editor magic and no hidden conversion — the migration files say what the columns are.

All DAB fields that carry `db_index`, `unique`, a `unique_together` entry, a `UniqueConstraint`, an `Index`, or membership in a composite primary key are `BoundedTextField`. The `ansible_base.E002` system check (registered under the `mssql` tag) errors if a `TextField` in an `ansible_base.*` app gains one of those constraints without being bounded, and `ansible_base.E004` errors when a key containing bounded fields exceeds SQL Server's index-key byte budget.

Consumer applications should apply the same rule to their own models: use `BoundedTextField` for constrained text columns, keep plain `TextField` for unbounded ones. See the [BoundedTextField documentation](lib/bounded-textfield.md) for length guidance and the adoption path.

## Other backend behavior

- The backend's compiler normalizes generated select aliases (`AS Col1` → `AS col1`) so sliced prefetch queries keep working under the case-sensitive collation; Django's outer `QUALIFY` wrapper references the lowercase form while mssql-django emits uppercase. This is a candidate for upstreaming to mssql-django.
- SQL Server stores `JSONField` values as `nvarchar(max)`. DAB omits the `ISJSON` check constraint on JSONField columns — for every JSONField, not only encrypted ones — so encrypted JSON values, which are ciphertext rather than valid JSON, can be stored.
- The backend enables mssql-django's `return_rows_bulk_insert` option by default, so `bulk_create()` populates primary keys (and other database-side defaults) on created objects, matching PostgreSQL. Set `OPTIONS['return_rows_bulk_insert'] = False` to opt out — required only if a managed table has an enabled trigger, because SQL Server rejects `OUTPUT` without `INTO` on trigger tables (mssql-django #130); DAB's own schema has no triggers.

## Where the SQL Server code lives

All SQL Server-specific code in DAB lives in two contained packages:

- `ansible_base/backends/mssql/` — the database engine (`base.py`), the compiler fix (`compiler.py`). Set `DATABASES[...]['ENGINE']` to `ansible_base.backends.mssql` to use it.
- `ansible_base/lib/mssql/` — library code for database-agnostic callers: vendor detection (`vendor.py`), `advisory_lock()`'s `sp_getapplock` implementation (`locks.py`), and `get_sql_server_notify_params()` for dispatcherd's Service Broker broker (`notify.py`).

`advisory_lock()` in `ansible_base.lib.utils.db` dispatches transparently by database vendor, so callers keep a single import; PostgreSQL uses advisory locks, SQL Server uses `sp_getapplock`, and SQLite is a no-op.

## The transparency floor

Application code uses the standard Django ORM — there is no `*_db_safe` parallel API to adopt. A small number of operations are not transparent on SQL Server, and are named here so developers know the boundary:

- `bulk_create(..., ignore_conflicts=True)` raises `NotSupportedError` on SQL Server (mssql-django does not implement it); DAB's own first-run `migrate` currently hits this in the `resource_registry` backfill (see Current status above). The remaining AAP-98732 work makes bulk writes transparent on SQL Server.
- `__regex`/`__iregex` lookups rely on a database function SQL Server does not install by default.
- `lock_session_timeout_milliseconds` means something different on SQL Server: on PostgreSQL it is an idle-session guard while the lock is held; on SQL Server it becomes the lock *acquisition* timeout (`sp_getapplock`'s `@LockTimeout`) and is ignored when `wait=False`. Callers that rely on the idle guard together with `wait=False` do not get that protection on SQL Server.
- Very large `pk__in` lists can exceed SQL Server's ~2100 query-parameter limit and need chunking; this cannot be made transparent and will remain a named, contained helper.

If the list of non-transparent operations grows beyond a handful, the design is revisited rather than extended.

## Testing

The repository's SQL Server test environment creates its database with `Latin1_General_100_CS_AS`. To run the full test suite against SQL Server, use `tox -e py312-mssql`; for PostgreSQL use `tox -e py312`. See [testing instructions](testing.md) for the test database setup.
