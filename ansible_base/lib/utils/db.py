import logging
from contextlib import contextmanager
from copy import deepcopy
from typing import Union
from zlib import crc32

import psycopg
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, OperationalError, connection, connections, transaction
from django.db.backends.postgresql.base import DatabaseWrapper as PsycopgDatabaseWrapper
from django.db.migrations.executor import MigrationExecutor

logger = logging.getLogger(__name__)
_MISSING_LOCK_ID = object()


def _close_lock_connection(db_connection):
    try:
        db_connection.close()
    except Exception:
        logger.exception("Failed to close database connection after advisory lock release failed")


def _close_lock_cursor(cursor):
    try:
        cursor.close()
    except Exception:
        logger.exception("Failed to close cursor during advisory lock cleanup")


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
                logger.exception("Failed to release advisory lock; discarding its database connection")
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


@contextmanager
def _postgres_advisory_lock(db_connection, lock_id, shared, wait, using, lock_session_timeout_milliseconds):
    """Acquire a PostgreSQL advisory lock and restore the caller's idle timeouts."""
    idle_in_transaction_session_timeout = None
    idle_session_timeout = None
    if lock_session_timeout_milliseconds > 0:
        with db_connection.cursor() as cursor:
            idle_in_transaction_session_timeout = cursor.execute("SHOW idle_in_transaction_session_timeout").fetchone()[0]
            idle_session_timeout = cursor.execute("SHOW idle_session_timeout").fetchone()[0]
            cursor.execute(
                "SET idle_in_transaction_session_timeout = %s",
                (lock_session_timeout_milliseconds,),
            )
            cursor.execute("SET idle_session_timeout = %s", (lock_session_timeout_milliseconds,))

    internal_error = False
    try:
        lock_args = () if lock_id is _MISSING_LOCK_ID else (lock_id,)
        with django_pglocks_advisory_lock(*lock_args, shared=shared, wait=wait, using=using) as acquired:
            yield acquired
    except OperationalError:
        # Suspected case is that timeout happened due to the given timeout
        # this is _expected_ to leave the connection in an unusable state, so dropping it is better
        logger.info("Dropping connection due to suspected timeout inside advisory_lock")
        db_connection.close_if_unusable_or_obsolete()
        internal_error = True
        raise
    finally:
        if not internal_error and lock_session_timeout_milliseconds > 0 and db_connection.connection is not None and not db_connection.closed_in_transaction:
            with db_connection.cursor() as cursor:
                cursor.execute(
                    "SET idle_in_transaction_session_timeout = %s",
                    (idle_in_transaction_session_timeout,),
                )
                cursor.execute("SET idle_session_timeout = %s", (idle_session_timeout,))


@contextmanager
def advisory_lock(
    lock_id=_MISSING_LOCK_ID,
    shared=False,
    wait=True,
    using=None,
    *,
    lock_session_timeout_milliseconds=0,
):
    """
    Context manager for database advisory locks.

    Supports PostgreSQL, MS SQL Server, and SQLite (no-op).
    Obtains a named lock identified by lock_id.

    Args:
        lock_id: Lock identifier (usually a string, int, or tuple)
        lock_session_timeout_milliseconds: Database-level timeout in milliseconds.
            On PostgreSQL this is an idle-session guard while the lock is held.
            On SQL Server it is instead the lock acquisition timeout (sp_getapplock
            @LockTimeout) and is ignored when wait=False.
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

    if db_connection.vendor == "postgresql":
        with _postgres_advisory_lock(
            db_connection,
            lock_id,
            shared,
            wait,
            using,
            lock_session_timeout_milliseconds,
        ) as acquired:
            yield acquired

    elif db_connection.vendor == "microsoft":
        # MS SQL Server implementation using sp_getapplock
        if lock_id is _MISSING_LOCK_ID:
            raise ValueError("advisory_lock requires a lock identifier")

        from ansible_base.lib.mssql.locks import mssql_advisory_lock_with_cleanup

        with mssql_advisory_lock_with_cleanup(
            db_connection,
            lock_id,
            shared,
            wait,
            using,
            lock_session_timeout_milliseconds,
        ) as acquired:
            yield acquired

    elif db_connection.vendor == "sqlite":
        # SQLite no-op - no distributed locking needed
        yield True

    else:
        raise RuntimeError(f"Advisory lock not implemented for database type {db_connection.vendor}")


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
