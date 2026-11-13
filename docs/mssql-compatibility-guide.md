# SQL Server compatibility and migration guide

django-ansible-base supports Microsoft SQL Server through the `ansible_base.backends.mssql` database engine, built on [mssql-django](https://github.com/microsoft/mssql-django). PostgreSQL remains the reference backend: every feature is developed and tested against PostgreSQL first, and the SQL Server support exists so that AAP components can run on either database. This guide covers the dependencies, collation, field, and backend behavior to review when deploying an application that uses DAB with SQL Server.

**Current status:** the backend, its DDL, the development environment, and the bulk-write data paths (AAP-98732) are complete — a first `manage.py migrate` succeeds on SQL Server, and the `py312-mssql` tox suite and CI matrix are green. Application code uses the standard Django ORM throughout; the small number of vendor-aware helpers is named in [the transparency floor](#the-transparency-floor) below.

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

- The backend's compiler forwards `with_col_aliases` to `pre_sql_setup()` the way Django's own compiler does (mssql-django drops it), so generated select aliases come out as the lowercase `col1`, `col2`... that Django's `QUALIFY` wrapper references. Without it, sliced prefetch and window-filter queries break under the case-sensitive collation. This is a candidate for upstreaming to mssql-django.
- SQL Server stores `JSONField` values as `nvarchar(max)`. DAB omits the `ISJSON` check constraint on JSONField columns — for every JSONField, not only encrypted ones — so encrypted JSON values, which are ciphertext rather than valid JSON, can be stored.
- The backend enables mssql-django's `return_rows_bulk_insert` option by default, so `bulk_create()` populates primary keys (and other database-side defaults) on created objects, matching PostgreSQL. Set `OPTIONS['return_rows_bulk_insert'] = False` to opt out — required only if a managed table has an enabled trigger, because SQL Server rejects `OUTPUT` without `INTO` on trigger tables (mssql-django #130); DAB's own schema has no triggers.

## Where the SQL Server code lives

All SQL Server-specific code in DAB lives in two contained packages:

- `ansible_base/backends/mssql/` — the database engine (`base.py`), the compiler fix (`compiler.py`). Set `DATABASES[...]['ENGINE']` to `ansible_base.backends.mssql` to use it.
- `ansible_base/lib/mssql/` — library code for database-agnostic callers: vendor detection (`vendor.py`), `advisory_lock()`'s `sp_getapplock` implementation (`locks.py`), transparent bulk writes (`bulk.py`), parameter-limit chunking (`params.py`), and the dispatcherd Service Broker helpers (`notify.py`).

`advisory_lock()` in `ansible_base.lib.utils.db` dispatches transparently by database vendor, so callers keep a single import; PostgreSQL uses advisory locks, SQL Server uses `sp_getapplock`, and SQLite is a no-op.

## Transparent bulk writes

`bulk_create(..., ignore_conflicts=True)` raises `NotSupportedError` on SQL Server (mssql-django does not implement it). DAB closes that gap at the manager layer: the shared abstract model bases (the `CommonModel` family — every DAB model, and any consumer model inheriting from them) carry `MSSQLSafeManager`, whose queryset rewrites `ignore_conflicts` bulk creates into an mssql-safe form, so application code keeps writing plain `model.objects.bulk_create(objs, ignore_conflicts=True)`. On PostgreSQL the manager is inert. Only duplicate-key conflicts are ignored — a foreign-key or check-constraint violation still raises, matching `ON CONFLICT DO NOTHING` semantics — and the fallback runs inside one transaction, so a failure never leaves a prefix of the rows committed (all-or-nothing, like the native statement).

One return-value difference remains: with `ignore_conflicts=True`, Django on PostgreSQL returns the input objects (without primary keys set), while the SQL Server path returns only the rows that were actually inserted, with primary keys populated. Code that uses the return value of `bulk_create(..., ignore_conflicts=True)` must not assume the same list on both vendors.

Historical models (the migration-state models used inside `migrate`) cannot take the manager — Django hands migration code plain managers. Migration utilities therefore use the function form, `ansible_base.lib.mssql.bulk.bulk_create(model, objs, ignore_conflicts=True)`, which applies the same dispatch by building the safe queryset directly (and so bypasses any custom manager on the model); on other vendors it delegates to the stock `bulk_create`. Both forms live in `ansible_base/lib/mssql/bulk.py`.

## Cascade deletes of object roles

Django's deletion collector NULLs nullable cascading foreign keys before deleting on databases that cannot defer constraint checks. For RBAC assignments this is wrong: nulling `object_role` turns object-scoped grants into global grants, and two grants with the same (actor, role definition) collide on the `unique_global_*_assignment` partial unique index. The explicit cleanup paths (object-deletion triggers, recompute, orphan cleanup) route through `delete_object_roles()` in `ansible_base/rbac/caching.py`, and the deletion entry points that would otherwise reach the collector with assignments still in place — `RoleDefinition.delete()`, `RoleDefinition.objects.filter(...).delete()`, `DABContentType.delete()`, and `DABContentType.objects.filter(...).delete()` — call it before running the collector cascade, inside one transaction so a failed delete leaves the grants in place. On SQL Server these remove the assignment rows first (inside a transaction, locking the object-role rows); on other vendors they are a passthrough to `queryset.delete()`.

## dispatcherd Service Broker connections

`get_sql_server_notify_params()` returns pyodbc connection parameters for dispatcherd's `sql_server` broker, and `get_sql_server_notify_conn_string()` renders the same settings as a ready-made ODBC connection string for dispatcherd versions whose `connect()` pops a `connection_string` from its config. Both apply `SQL_SERVER_NOTIFY_DATABASES` overrides on top of the Django `DATABASES` entry. The Service Broker listener holds a long-lived connection, so give it its own pool bucket — set `SQL_SERVER_NOTIFY_DATABASES` to point at a distinct application name (the ODBC `APP`/`application_name` keyword) and bypass external poolers for it, the same way a pg LISTEN connection bypasses PgBouncer.

## The transparency floor

Application code uses the standard Django ORM — there is no `*_db_safe` parallel API to adopt. A small number of operations are not transparent on SQL Server, and are named here so developers know the boundary:

- `__regex`/`__iregex` lookups are not supported on SQL Server. `rest_filters` rejects them with a `ParseError` ("Regular expression lookups are not supported on SQL Server"); DAB's own code paths that need word-boundary matching (OIDC scope checks) narrow with `__contains` and apply the regex Python-side.
- SQL Server caps a single query at ~2100 bound parameters. Plain `__in` lookups do not need help — mssql-django routes them through a temp table — but OR-ed `Q` pairs and `Case`/`When` expressions bind every value inline. DAB's internal batch paths use `in_chunks()` from `ansible_base.lib.mssql.params` for those; consumer code doing the same shapes should too.
- `Cast` per query: SQL Server comparisons between `nvarchar` and typed columns do not implicitly convert the way PostgreSQL casts text, so `ansible_base/rbac/evaluations.py` wraps its cross-type `object_id` comparisons in explicit `Cast`s. These are vendor-neutral ORM and run unchanged on PostgreSQL.
- `lock_session_timeout_milliseconds` means something different on SQL Server: on PostgreSQL it is an idle-session guard while the lock is held; on SQL Server it becomes the lock *acquisition* timeout (`sp_getapplock`'s `@LockTimeout`) and is ignored when `wait=False`. Callers that rely on the idle guard together with `wait=False` do not get that protection on SQL Server.

If the list of non-transparent operations grows beyond a handful, the design is revisited rather than extended.

## Testing

The repository's SQL Server test environment creates its database with `Latin1_General_100_CS_AS`. To run the full test suite against SQL Server, use `tox -e py312-mssql`; for PostgreSQL use `tox -e py312`. See [testing instructions](testing.md) for the test database setup.
