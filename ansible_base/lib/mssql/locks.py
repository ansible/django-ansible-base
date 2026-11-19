import logging
from contextlib import contextmanager
from zlib import crc32

from django.db import DEFAULT_DB_ALIAS, OperationalError, connections

from ansible_base.lib.utils.db import _advisory_lock_scope, _close_lock_cursor

logger = logging.getLogger(__name__)


def convert_lock_id_to_resource_name(lock_id):
    """
    Convert PostgreSQL-style lock ID to MS SQL Server resource name.

    PostgreSQL accepts integers, tuples of integers, or strings.
    MS SQL Server requires nvarchar resource names (max 255 chars).

    String lock ids keep a readable (truncated) prefix plus a crc32 digest of
    the full string: plain truncation would make distinct lock ids share a
    lock, and an unhashed string could collide with the int/tuple forms below.
    This mirrors the PostgreSQL path, which hashes the whole string while
    using integer ids as-is.

    Args:
        lock_id: int, str, or tuple/list of ints

    Returns:
        str: Resource name for sp_getapplock

    Raises:
        ValueError: If tuple/list has wrong length or non-integer elements
    """
    if isinstance(lock_id, str):
        digest = str(crc32(lock_id.encode("utf-8")))
        return lock_id[: 255 - len(digest)] + digest
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
def mssql_advisory_lock(lock_id, shared=False, wait=True, lock_session_timeout_milliseconds=0, using=None):
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
    resource_name = convert_lock_id_to_resource_name(lock_id)

    # Determine lock mode
    lock_mode = "Shared" if shared else "Exclusive"

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

    # conn.cursor() establishes the connection for this thread if needed
    conn = connections[using]
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
        # (no SET NOCOUNT here: it is a session-level setting and would leak onto the
        # pooled connection, where it breaks row counts for Django's update()/delete())
        # SQL Server application locks are visible across connections regardless of LockOwner
        # Use 'Session' as default - 'Transaction' requires an active transaction
        sql = """
            DECLARE @result int;
            EXEC @result = sp_getapplock @Resource=%s, @LockMode=%s, @LockTimeout=%s, @LockOwner='Session';
            SELECT @result AS lock_result;
        """
        cursor.execute(sql, [resource_name, lock_mode, timeout])
        row = cursor.fetchone()
        if row is None:
            raise OperationalError(f"MS SQL sp_getapplock returned no result for resource {resource_name}")
        result = row[0]

        if result >= 0:
            # Lock acquired (0 or 1)
            acquired = True
        elif result == -1:
            if wait:
                raise OperationalError(f"MS SQL sp_getapplock timed out for resource {resource_name}")
            acquired = False
        else:
            # Other errors (-2, -3, -999)
            raise OperationalError(f"MS SQL sp_getapplock failed with code {result} for resource {resource_name}")
    except BaseException:
        _close_lock_cursor(cursor)
        raise

    def release_lock():
        cursor.execute("EXEC sp_releaseapplock @Resource=%s, @LockOwner='Session'", [resource_name])

    with _advisory_lock_scope(cursor, conn, acquired, release_lock):
        yield acquired


@contextmanager
def mssql_advisory_lock_with_cleanup(db_connection, lock_id, shared, wait, using, lock_session_timeout_milliseconds):
    """Acquire a SQL Server application lock and close unusable connections on errors."""
    try:
        with mssql_advisory_lock(
            lock_id,
            shared=shared,
            wait=wait,
            lock_session_timeout_milliseconds=lock_session_timeout_milliseconds,
            using=using,
        ) as acquired:
            yield acquired
    except OperationalError:
        logger.info("Dropping connection due to error inside MS SQL advisory_lock")
        db_connection.close_if_unusable_or_obsolete()
        raise
