import logging
from contextlib import contextmanager
from copy import deepcopy
from typing import Union
from zlib import crc32

import psycopg
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, IntegrityError, OperationalError, connection, connections, router, transaction
from django.db.backends.postgresql.base import DatabaseWrapper as PsycopgDatabaseWrapper
from django.db.migrations.executor import MigrationExecutor
from django.db.models import AutoField

# MS SQL Server raises pyodbc.IntegrityError which is not caught by django.db.IntegrityError
try:
    import pyodbc

    DatabaseIntegrityError = (IntegrityError, pyodbc.IntegrityError)
except ImportError:
    DatabaseIntegrityError = (IntegrityError,)

logger = logging.getLogger(__name__)
_MISSING_LOCK_ID = object()


def _close_lock_connection(db_connection):
    try:
        db_connection.close()
    except Exception:
        logger.exception('Failed to close database connection after advisory lock release failed')


def _close_lock_cursor(cursor):
    try:
        cursor.close()
    except Exception:
        logger.exception('Failed to close cursor during advisory lock cleanup')


@contextmanager
def _advisory_lock_scope(cursor, db_connection, acquired, release_lock):
    """Release a session lock without replacing an exception from the protected body."""
    try:
        yield acquired
    except BaseException:
        if acquired:
            try:
                release_lock()
            except Exception:
                logger.exception('Failed to release advisory lock; discarding its database connection')
                _close_lock_connection(db_connection)
        _close_lock_cursor(cursor)
        raise
    else:
        try:
            if acquired:
                release_lock()
        except Exception:
            _close_lock_connection(db_connection)
            _close_lock_cursor(cursor)
            raise
        cursor.close()


@contextmanager
def ensure_transaction():
    needs_new_transaction = not transaction.get_connection().in_atomic_block

    if needs_new_transaction:
        with transaction.atomic():
            yield
    else:
        yield


def migrations_are_complete() -> bool:
    """Returns a boolean telling you if manage.py migrate has been run to completion

    Note that this is a little expensive, like up to 20 database queries
    and lots of imports.
    Not suitable to run as part of a request, but expected to be okay
    in a management command or post_migrate signals"""
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return not bool(plan)


# NOTE: the django_pglocks_advisory_lock context manager was forked from the django-pglocks v1.0.4
# that was licensed under the MIT license


@contextmanager
def django_pglocks_advisory_lock(lock_id, shared=False, wait=True, using=None):

    if using is None:
        using = DEFAULT_DB_ALIAS

    # Assemble the function name based on the options.

    function_name = 'pg_'

    if not wait:
        function_name += 'try_'

    function_name += 'advisory_lock'

    if shared:
        function_name += '_shared'

    release_function_name = 'pg_advisory_unlock'
    if shared:
        release_function_name += '_shared'

    # Format up the parameters.

    tuple_format = False

    if isinstance(
        lock_id,
        (
            list,
            tuple,
        ),
    ):
        if len(lock_id) != 2:
            raise ValueError("Tuples and lists as lock IDs must have exactly two entries.")

        if not isinstance(lock_id[0], int) or not isinstance(lock_id[1], int):
            raise ValueError("Both members of a tuple/list lock ID must be integers")

        tuple_format = True
    elif isinstance(lock_id, str):
        # Generates an id within postgres integer range (-2^31 to 2^31 - 1).
        # crc32 generates an unsigned integer in Py3, we convert it into
        # a signed integer using 2's complement (this is a noop in Py2)
        pos = crc32(lock_id.encode("utf-8"))
        lock_id = (2**31 - 1) & pos
        if pos & 2**31:
            lock_id -= 2**31
    elif not isinstance(lock_id, int):
        raise ValueError("Cannot use %s as a lock id" % lock_id)

    if tuple_format:
        base = "SELECT %s(%d, %d)"
        params = (
            lock_id[0],
            lock_id[1],
        )
    else:
        base = "SELECT %s(%d)"
        params = (lock_id,)

    acquire_params = (function_name,) + params

    command = base % acquire_params
    db_connection = connections[using]
    cursor = db_connection.cursor()

    try:
        cursor.execute(command)

        if not wait:
            acquired = cursor.fetchone()[0]
        else:
            acquired = True
    except BaseException:
        _close_lock_cursor(cursor)
        raise

    release_params = (release_function_name,) + params
    release_command = base % release_params

    def release_lock():
        cursor.execute(release_command)

    with _advisory_lock_scope(cursor, db_connection, acquired, release_lock):
        yield acquired


def _convert_lock_id_to_resource_name(lock_id):
    """
    Convert PostgreSQL-style lock ID to MS SQL Server resource name.

    PostgreSQL accepts integers, tuples of integers, or strings.
    MS SQL Server requires nvarchar resource names (max 255 chars).

    Args:
        lock_id: int, str, or tuple/list of ints

    Returns:
        str: Resource name for sp_getapplock

    Raises:
        ValueError: If tuple/list has wrong length or non-integer elements
    """
    if isinstance(lock_id, str):
        # Already a string - truncate to 255 chars if needed
        return lock_id[:255]
    elif isinstance(lock_id, int):
        return f"dab_lock_{lock_id}"
    elif isinstance(lock_id, (list, tuple)):
        # Match PostgreSQL validation: must have exactly 2 integer elements
        if len(lock_id) != 2:
            raise ValueError("Tuples and lists as lock IDs must have exactly two entries.")
        if not isinstance(lock_id[0], int) or not isinstance(lock_id[1], int):
            raise ValueError("Both members of a tuple/list lock ID must be integers")
        # Join tuple elements with underscore
        return f"dab_lock_{lock_id[0]}_{lock_id[1]}"
    else:
        # Fall back to hash for other types
        pos = crc32(str(lock_id).encode("utf-8"))
        return f"dab_lock_{pos}"


@contextmanager
def _mssql_advisory_lock(lock_id, shared=False, wait=True, lock_session_timeout_milliseconds=0, using=None):
    """
    MS SQL Server advisory lock implementation using sp_getapplock.

    Args:
        lock_id: Lock identifier (converted to resource name)
        shared: If True, use Shared lock mode; otherwise Exclusive
        wait: If False, fail immediately if lock unavailable
        lock_session_timeout_milliseconds: Lock timeout in milliseconds
        using: Django database alias

    Yields:
        bool: True if lock acquired, False if not (when wait=False)
    """
    if using is None:
        using = DEFAULT_DB_ALIAS

    # Convert lock ID to resource name
    resource_name = _convert_lock_id_to_resource_name(lock_id)

    # Determine lock mode
    lock_mode = 'Shared' if shared else 'Exclusive'

    # Determine timeout
    # -1 = wait indefinitely (default)
    # 0 = return immediately if locked
    # >0 = wait up to N milliseconds
    if not wait:
        timeout = 0
    elif lock_session_timeout_milliseconds > 0:
        timeout = lock_session_timeout_milliseconds
    else:
        timeout = -1  # Wait indefinitely

    # Ensure connection is properly established for this thread
    conn = connections[using]
    if conn.connection is None:
        conn.ensure_connection()

    cursor = conn.cursor()
    acquired = False

    try:
        # sp_getapplock return values:
        # 0 = lock granted immediately
        # 1 = lock granted after waiting
        # -1 = timeout
        # -2 = canceled
        # -3 = deadlock victim
        # -999 = parameter validation or other error
        # SQL Server sp_getapplock: execute and fetch result in separate steps
        # Using SET NOCOUNT ON to suppress row count messages that can interfere with result retrieval
        # SQL Server application locks are visible across connections regardless of LockOwner
        # Use 'Session' as default - 'Transaction' requires an active transaction
        sql = """
            SET NOCOUNT ON;
            DECLARE @result int;
            EXEC @result = sp_getapplock @Resource=%s, @LockMode=%s, @LockTimeout=%s, @LockOwner='Session';
            SELECT @result AS lock_result;
        """
        try:
            cursor.execute(sql, [resource_name, lock_mode, timeout])
            row = cursor.fetchone()
            result = row[0] if row else -999
        except Exception:
            logger.exception(f'MS SQL sp_getapplock query failed for resource {resource_name}')
            result = -999

        if result >= 0:
            # Lock acquired (0 or 1)
            acquired = True
        elif result == -1:
            if wait:
                raise OperationalError(f'MS SQL sp_getapplock timed out for resource {resource_name}')
            acquired = False
        else:
            # Other errors (-2, -3, -999)
            raise OperationalError(f'MS SQL sp_getapplock failed with code {result} for resource {resource_name}')
    except BaseException:
        _close_lock_cursor(cursor)
        raise

    def release_lock():
        cursor.execute("EXEC sp_releaseapplock @Resource=%s, @LockOwner='Session'", [resource_name])

    with _advisory_lock_scope(cursor, conn, acquired, release_lock):
        yield acquired


@contextmanager
def advisory_lock(lock_id=_MISSING_LOCK_ID, shared=False, wait=True, using=None, *, lock_session_timeout_milliseconds=0):
    """
    Context manager for database advisory locks.

    Supports PostgreSQL, MS SQL Server, and SQLite (no-op).
    Obtains a named lock identified by lock_id.

    Args:
        lock_id: Lock identifier (usually a string, int, or tuple)
        lock_session_timeout_milliseconds: Database-level timeout in milliseconds
        shared: If True, allow shared locks
        wait: If True, block until lock is obtained
        using: Django database alias

    Yields:
        bool: True if lock acquired, False if not (when wait=False)

    Raises:
        RuntimeError: If database vendor is not supported
        OperationalError: If lock operation fails

    Examples:
        # Exclusive lock
        with advisory_lock('my_lock'):
            # Critical section

        # Shared lock with timeout
        with advisory_lock('my_lock', shared=True, lock_session_timeout_milliseconds=5000) as acquired:
            if acquired:
                # Lock acquired
                pass

        # Try-lock (non-blocking)
        with advisory_lock('my_lock', wait=False) as acquired:
            if acquired:
                # Got the lock
                pass
    """
    using = using or DEFAULT_DB_ALIAS
    db_connection = connections[using]
    internal_error = False

    if db_connection.vendor == "postgresql":
        # PostgreSQL implementation using pg_advisory_lock
        cur = None
        idle_in_transaction_session_timeout = None
        idle_session_timeout = None
        if lock_session_timeout_milliseconds > 0:
            with db_connection.cursor() as cur:
                idle_in_transaction_session_timeout = cur.execute("SHOW idle_in_transaction_session_timeout").fetchone()[0]
                idle_session_timeout = cur.execute("SHOW idle_session_timeout").fetchone()[0]
                cur.execute("SET idle_in_transaction_session_timeout = %s", (lock_session_timeout_milliseconds,))
                cur.execute("SET idle_session_timeout = %s", (lock_session_timeout_milliseconds,))

        try:
            lock_args = () if lock_id is _MISSING_LOCK_ID else (lock_id,)
            with django_pglocks_advisory_lock(*lock_args, shared=shared, wait=wait, using=using) as internal_lock:
                yield internal_lock
        except OperationalError:
            # Suspected case is that timeout happened due to the given timeout
            # this is _expected_ to leave the connection in an unusable state, so dropping it is better
            logger.info('Dropping connection due to suspected timeout inside advisory_lock')
            db_connection.close_if_unusable_or_obsolete()
            internal_error = True
            raise
        finally:
            if (
                not internal_error
                and lock_session_timeout_milliseconds > 0
                and db_connection.connection is not None
                and not db_connection.closed_in_transaction
            ):
                with db_connection.cursor() as cur:
                    cur.execute("SET idle_in_transaction_session_timeout = %s", (idle_in_transaction_session_timeout,))
                    cur.execute("SET idle_session_timeout = %s", (idle_session_timeout,))

    elif db_connection.vendor == "microsoft":
        # MS SQL Server implementation using sp_getapplock
        if lock_id is _MISSING_LOCK_ID:
            raise ValueError("advisory_lock requires a lock identifier")

        try:
            with _mssql_advisory_lock(
                lock_id,
                shared=shared,
                wait=wait,
                lock_session_timeout_milliseconds=lock_session_timeout_milliseconds,
                using=using,
            ) as internal_lock:
                yield internal_lock
        except OperationalError:
            logger.info('Dropping connection due to error inside MS SQL advisory_lock')
            db_connection.close_if_unusable_or_obsolete()
            internal_error = True
            raise

    elif db_connection.vendor == "sqlite":
        # SQLite no-op - no distributed locking needed
        yield True

    else:
        raise RuntimeError(f'Advisory lock not implemented for database type {db_connection.vendor}')


# Django settings.DATABASES['alias'] dictionary type
dj_db_dict = dict[str, Union[str, int]]


def psycopg_connection_from_django(**kwargs) -> psycopg.Connection:
    """Compatibility with dispatcherd connection factory, just returns the Django connection

    dispatcherd passes config info as kwargs, but in this case we just want to ignore then.
    Because the point of this it to not reconnect, but rely on existing Django connection management.
    """
    if connection.connection is None:
        connection.ensure_connection()
    return connection.connection


def psycopg_kwargs_from_settings_dict(settings_dict: dj_db_dict) -> dict:
    """Return psycopg connection creation kwargs given Django db settings info

    :param dict setting_dict: DATABASES in Django settings
    :return: kwargs that can be passed to psycopg.connect, or connection classes"""
    psycopg_params = PsycopgDatabaseWrapper(settings_dict).get_connection_params().copy()
    psycopg_params.pop('cursor_factory', None)
    psycopg_params.pop('context', None)
    return psycopg_params


def psycopg_conn_string_from_settings_dict(settings_dict: dj_db_dict) -> str:
    """Returns a string that psycopg can take as conninfo for Connection class.

    Example return value: "dbname=postgres user=postgres"
    """
    conn_params = psycopg_kwargs_from_settings_dict(settings_dict)
    return psycopg.conninfo.make_conninfo(**conn_params)


def combine_settings_dict(settings_dict1: dj_db_dict, settings_dict2: dj_db_dict, **extra_options) -> dj_db_dict:
    """Given two Django database settings dictionaries, combine them and return a new settings_dict"""
    settings_dict = deepcopy(settings_dict1)

    # Apply overrides specifically for the listener connection
    for k, v in settings_dict2.items():
        if k != 'OPTIONS':
            settings_dict[k] = v

    # Merge the database OPTIONS
    # https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-connection-settings
    # These are not expected to be nested, as they are psycopg params
    settings_dict.setdefault('OPTIONS', {})
    # extra_options are used by AWX to set application_name, which is generally a good idea
    settings_dict['OPTIONS'].update(extra_options)
    # Apply overrides from nested OPTIONS for the listener connection
    for k, v in settings_dict2.get('OPTIONS', {}).items():
        settings_dict['OPTIONS'][k] = v  # type: ignore[index]

    return settings_dict


def get_pg_notify_params(alias: str = DEFAULT_DB_ALIAS, **extra_options) -> dict:
    """Returns a dictionary that can be used as kwargs to create a psycopg.Connection

    This should use the same connection parameters as Django does.
    However, this also allows overrides specified by
    - PG_NOTIFY_DATABASES, higher precedence, preferred setting
    - LISTENER_DATABASES, lower precedence, deprecated AWX setting.
    """
    pg_notify_overrides = {}
    if hasattr(settings, 'PG_NOTIFY_DATABASES'):
        pg_notify_overrides = settings.PG_NOTIFY_DATABASES.get(alias, {})
    elif hasattr(settings, 'LISTENER_DATABASES'):
        pg_notify_overrides = settings.LISTENER_DATABASES.get(alias, {})

    settings_dict = combine_settings_dict(settings.DATABASES[alias], pg_notify_overrides, **extra_options)

    # Reuse the Django postgres DB backend to create params for the psycopg library
    psycopg_params = psycopg_kwargs_from_settings_dict(settings_dict)

    return psycopg_params


def get_sql_server_notify_params(alias: str = DEFAULT_DB_ALIAS, **extra_options) -> dict:
    """
    Returns connection parameters for MS SQL Server Service Broker (dispatcherd sql_server broker).

    Similar to get_pg_notify_params() but for MS SQL Server. Consumer applications (Controller, Gateway,
    EDA) use these parameters to configure dispatcherd's sql_server broker to replace pg_notify.

    This uses the same connection parameters as Django's DATABASES configuration, with optional
    overrides specified by SQL_SERVER_NOTIFY_DATABASES setting (parallel to PG_NOTIFY_DATABASES).

    Args:
        alias: Django database alias (default: 'default')
        **extra_options: Additional connection options to merge (e.g., application_name)

    Returns:
        dict: pyodbc-compatible connection parameters for dispatcherd

    Example:
        # In consumer app (Controller, Gateway, EDA) dispatcherd configuration:
        from django.db import connection
        from ansible_base.lib.utils.db import get_sql_server_notify_params

        if connection.vendor == "microsoft":
            broker_config = {
                "sql_server": {
                    "config": get_sql_server_notify_params(),
                }
            }

    Part of ANSTRAT-1887 (P1): Replace PostgreSQL NOTIFY/LISTEN for MS SQL deployments.
    """
    sql_server_overrides = {}
    if hasattr(settings, 'SQL_SERVER_NOTIFY_DATABASES'):
        sql_server_overrides = settings.SQL_SERVER_NOTIFY_DATABASES.get(alias, {})

    settings_dict = combine_settings_dict(settings.DATABASES[alias], sql_server_overrides, **extra_options)

    # Extract pyodbc connection parameters from Django settings
    params = {
        'server': settings_dict.get('HOST') or 'localhost',
        'port': settings_dict.get('PORT') or 1433,
        'database': settings_dict.get('NAME'),
        'user': settings_dict.get('USER'),
        'password': settings_dict.get('PASSWORD'),
    }

    # Add OPTIONS if present (driver, extra_params, etc.)
    if 'OPTIONS' in settings_dict:
        params.update(settings_dict['OPTIONS'])

    return params


def _bulk_create_using_manager(manager, objects, using, ignore_conflicts):
    created = manager.bulk_create(objects, ignore_conflicts=ignore_conflicts) or []
    for obj in created:
        if ignore_conflicts or obj._state.db is None:
            obj._state.db = using
        obj._state.adding = False
    return created


def _bulk_insert_one(manager, model_class, obj, using, return_ids):
    """Insert one object without calling its model save override or save signals."""
    queryset = manager.get_queryset()
    queryset._prepare_for_bulk_create([obj])
    opts = model_class._meta
    fields = [field for field in opts.concrete_fields if not field.generated]
    pk_is_set = obj._is_pk_set() if hasattr(obj, '_is_pk_set') else getattr(obj, opts.pk.attname, None) is not None
    if not pk_is_set:
        fields = [field for field in fields if not isinstance(field, AutoField)]

    returning_fields = opts.db_returning_fields if return_ids else ()
    returned_rows = queryset._insert([obj], fields, using=using, returning_fields=returning_fields)
    for returned_row in returned_rows:
        for value, field in zip(returned_row, returning_fields):
            setattr(obj, field.attname, value)
    obj._state.db = using
    obj._state.adding = False
    return obj


def _bulk_create_with_savepoints(manager, model_class, objects, using):
    """Insert individually inside batched savepoints when generated IDs are needed."""
    created = []
    for start in range(0, len(objects), 50):
        batch = objects[start : start + 50]
        savepoint_id = transaction.savepoint(using=using)
        try:
            for obj in batch:
                created.append(_bulk_insert_one(manager, model_class, obj, using, return_ids=True))
            transaction.savepoint_commit(savepoint_id, using=using)
        except Exception:
            transaction.savepoint_rollback(savepoint_id, using=using)
            raise
    return created


def _bulk_create_ignoring_conflicts(model_class, manager, objects, using, db_connection, return_ids):
    """Try a batch insert when IDs aren't needed, then retry rows to skip conflicts."""
    created = []
    if not return_ids:
        savepoint_id = transaction.savepoint(using=using)
        try:
            created = _bulk_create_using_manager(manager, objects, using, ignore_conflicts=False)
            transaction.savepoint_commit(savepoint_id, using=using)
            return created
        except DatabaseIntegrityError as exc:
            logger.debug(f"bulk_create_db_safe: Batch insert conflicted for {model_class.__name__}: {exc}")
            db_connection.needs_rollback = False
            transaction.savepoint_rollback(savepoint_id, using=using)
        except Exception:
            transaction.savepoint_rollback(savepoint_id, using=using)
            raise

    for obj in objects:
        savepoint_id = transaction.savepoint(using=using)
        try:
            created.append(_bulk_insert_one(manager, model_class, obj, using, return_ids=return_ids))
            transaction.savepoint_commit(savepoint_id, using=using)
        except DatabaseIntegrityError as exc:
            logger.debug(f"bulk_create_db_safe: Caught IntegrityError for {model_class.__name__}: {exc}")
            db_connection.needs_rollback = False
            transaction.savepoint_rollback(savepoint_id, using=using)
        except Exception:
            transaction.savepoint_rollback(savepoint_id, using=using)
            raise
    return created


def bulk_create_db_safe(model_class, objects, ignore_conflicts=True, using=None, return_ids=True):
    """
    Database-safe bulk_create that works on both PostgreSQL and MS SQL Server.

    Use this instead of Model.objects.bulk_create() when using ignore_conflicts,
    as MS SQL Server doesn't support native conflict ignoring.

    PostgreSQL: Uses native ignore_conflicts support (no behavior change)
    MS SQL Server: Uses a batch insert when generated IDs aren't needed. When
    IDs are required, inserts one row at a time so SQL Server can return each
    identity value without calling model save overrides or mutating signal lists.

    Args:
        model_class: Model class to create objects for
        objects: List of model instances to create
        ignore_conflicts: If True, ignore conflicts. If False, let them raise (default: True)
        using: Database alias to use (optional)
        return_ids: Whether callers require generated primary keys on returned objects.

    Returns:
        List of created objects (may be empty if all conflicts ignored)

    Example:
        # Instead of:
        # MyModel.objects.bulk_create(items, ignore_conflicts=True)

        # Use:
        bulk_create_db_safe(MyModel, items, ignore_conflicts=True)

        # With database alias:
        bulk_create_db_safe(MyModel, items, using='replica')

    Note:
        Like bulk_create(), this function does NOT fire post_save signals.
        Callers are responsible for firing signals if needed. When ``return_ids``
        is False, generated primary keys may remain unset on backends that cannot
        return them from a multi-row insert.
    """
    if not objects:
        return []

    if using is None:
        using = router.db_for_write(model_class)
    manager = model_class.objects.db_manager(using)

    # Get connection for the specified database
    db_connection = connections[using]

    if ignore_conflicts:
        if not db_connection.features.supports_ignore_conflicts:
            return _bulk_create_ignoring_conflicts(model_class, manager, objects, using, db_connection, return_ids)
        return _bulk_create_using_manager(manager, objects, using, ignore_conflicts=True)

    if not return_ids:
        return _bulk_create_using_manager(manager, objects, using, ignore_conflicts=False)

    if not db_connection.features.can_return_rows_from_bulk_insert:
        return _bulk_create_with_savepoints(manager, model_class, objects, using)
    return _bulk_create_using_manager(manager, objects, using, ignore_conflicts=False)
