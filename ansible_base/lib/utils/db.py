import logging
import re
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

_SAFE_IDENTIFIER_RE = re.compile(r'^[A-Za-z_]\w*$')


def _render_identifier(vendor: str, name: str):
    """Render a SQL identifier for the given database vendor."""
    if vendor == 'postgresql':
        return psycopg.sql.Identifier(name)
    elif vendor == 'sqlite':
        if not _SAFE_IDENTIFIER_RE.match(name):
            raise ValueError(f"Unsafe SQL identifier: {name!r}")
        return f'"{name}"'
    else:
        raise RuntimeError(f"Database vendor {vendor!r} is not supported by build_safe_sql")


def _render_placeholder(vendor: str):
    """Render a single value placeholder for the given database vendor."""
    if vendor == 'postgresql':
        return psycopg.sql.Placeholder()
    elif vendor == 'sqlite':
        return '%s'
    else:
        raise RuntimeError(f"Database vendor {vendor!r} is not supported by build_safe_sql")


def _render_params(vendor: str, count: int):
    """Render multiple value placeholders for the given database vendor."""
    if vendor == 'postgresql':
        return psycopg.sql.SQL(',').join([psycopg.sql.Placeholder()] * count)
    elif vendor == 'sqlite':
        return ','.join(['%s'] * count)
    else:
        raise RuntimeError(f"Database vendor {vendor!r} is not supported by build_safe_sql")


_MARKER_RE = re.compile(r'\{([IPip]?)\}')


def _resolve_markers(vendor: str, template: str, slots: list) -> list:
    """Parse template markers and resolve each to a vendor-specific SQL part.

    ``{I}`` and ``{P}`` markers consume the next item from ``slots``;
    ``{}`` markers emit a single value placeholder without consuming a slot.
    """
    markers = _MARKER_RE.findall(template)
    expected_slots = sum(1 for m in markers if m.upper() in ('I', 'P'))
    if expected_slots != len(slots):
        raise ValueError(f"Template has {expected_slots} {{I}}/{{P}} marker(s) but got {len(slots)} slot(s)")

    parts = []
    slot_iter = iter(slots)
    for marker in markers:
        marker_upper = marker.upper()
        if marker_upper == 'I':
            name = next(slot_iter)
            if not isinstance(name, str):
                raise TypeError(f"{{I}} marker expects str, got {type(name).__name__}")
            parts.append(_render_identifier(vendor, name))
        elif marker_upper == 'P':
            count = next(slot_iter)
            if not isinstance(count, int):
                raise TypeError(f"{{P}} marker expects int, got {type(count).__name__}")
            if count <= 0:
                raise ValueError(f"Placeholder count must be positive, got {count}")
            parts.append(_render_params(vendor, count))
        else:
            parts.append(_render_placeholder(vendor))
    return parts


def build_safe_sql(vendor: str, template: str, slots: list) -> str:
    """Build a safe SQL string with quoted identifiers and parameterized placeholders.

    The template uses typed markers for slot substitution:

    - ``{I}`` — SQL identifier (table/column name). Consumes the next
      ``str`` from ``slots``, validates it, and quotes it.
    - ``{P}`` — placeholder list. Consumes the next ``int`` from ``slots``
      and expands to that many comma-separated ``%s`` placeholders.
    - ``{}``  — single value placeholder. Emits one ``%s`` without
      consuming a slot.

    Args:
        vendor: Database vendor string (e.g. ``connection.vendor``).
        template: A SQL template using ``{I}``, ``{P}``, and ``{}`` markers.
        slots: An ordered list consumed left-to-right by ``{I}`` and ``{P}``
            markers. ``str`` items are identifiers, ``int`` items are
            placeholder counts.

    Returns:
        A SQL string safe for ``cursor.execute(sql, params)``.

    Example::

        build_safe_sql(
            connection.vendor,
            "DELETE FROM {I} WHERE {I} = {} AND {I} IN ({P})",
            [table, 'content_type_id', 'object_id', len(pks)],
        )

    Raises:
        ValueError: If slots don't match markers, an identifier is unsafe,
            or a placeholder count is not positive.
        TypeError: If a slot has the wrong type for its marker.
        RuntimeError: If the database vendor is not supported.
    """
    parts = _resolve_markers(vendor, template, slots)

    if vendor == 'postgresql':
        pg_template = _MARKER_RE.sub('{}', template)
        return psycopg.sql.SQL(pg_template).format(*parts).as_string(None)
    elif vendor == 'sqlite':
        segments = _MARKER_RE.split(template)
        result = []
        part_idx = 0
        for segment in segments:
            if segment.upper() in ('', 'I', 'P'):
                if part_idx < len(parts):
                    result.append(parts[part_idx])
                    part_idx += 1
            else:
                result.append(segment)
        return ''.join(result)
    else:
        raise RuntimeError(f"Database vendor {vendor!r} is not supported by build_safe_sql")


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
    cursor = connections[using].cursor()

    cursor.execute(command)

    if not wait:
        acquired = cursor.fetchone()[0]
    else:
        acquired = True

    try:
        yield acquired
    finally:
        if acquired:
            release_params = (release_function_name,) + params

            command = base % release_params
            cursor.execute(command)

        cursor.close()


@contextmanager
def advisory_lock(*args, lock_session_timeout_milliseconds=0, **kwargs):
    """Context manager that wraps the pglocks advisory lock

    This obtains a named lock in postgres, idenfied by the args passed in
    usually the lock identifier is a simple string.

    @param: wait If True, block until the lock is obtained
    @param: shared Whether or not the lock is shared
    @param: lock_session_timeout_milliseconds Postgres-level timeout
    @param: using django database identifier
    """
    internal_error = False
    if connection.vendor == "postgresql":
        cur = None
        idle_in_transaction_session_timeout = None
        idle_session_timeout = None
        if lock_session_timeout_milliseconds > 0:
            with connection.cursor() as cur:
                idle_in_transaction_session_timeout = cur.execute("SHOW idle_in_transaction_session_timeout").fetchone()[0]
                idle_session_timeout = cur.execute("SHOW idle_session_timeout").fetchone()[0]
                cur.execute("SET idle_in_transaction_session_timeout = %s", (lock_session_timeout_milliseconds,))
                cur.execute("SET idle_session_timeout = %s", (lock_session_timeout_milliseconds,))

        try:
            with django_pglocks_advisory_lock(*args, **kwargs) as internal_lock:
                yield internal_lock
        except OperationalError:
            # Suspected case is that timeout happened due to the given timeout
            # this is _expected_ to leave the connection in an unusable state, so dropping it is better
            logger.info('Dropping connection due to suspected timeout inside advisory_lock')
            connection.close_if_unusable_or_obsolete()
            internal_error = True
            raise
        finally:
            if (not internal_error) and lock_session_timeout_milliseconds > 0:
                with connection.cursor() as cur:
                    cur.execute("SET idle_in_transaction_session_timeout = %s", (idle_in_transaction_session_timeout,))
                    cur.execute("SET idle_session_timeout = %s", (idle_session_timeout,))

    elif connection.vendor == "sqlite":
        yield True
    else:
        raise RuntimeError(f'Advisory lock not implemented for database type {connection.vendor}')


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
        settings_dict['OPTIONS'][k] = v

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
