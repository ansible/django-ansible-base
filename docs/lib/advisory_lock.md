# Advisory Locks

## Overview

Django-ansible-base provides `advisory_lock()`, a database-agnostic context manager for application-level locking coordination. Advisory locks allow processes to synchronize access to shared resources without requiring actual table rows.

This utility supports:
- **PostgreSQL** (via `pg_advisory_lock`)
- **MS SQL Server** (via `sp_getapplock`)
- **SQLite** (no-op, always returns `True`)

The implementation follows the same contract as [django-pglocks](https://pypi.org/project/django-pglocks/), with extensions for production use discovered through deployment in AWX:
- SQLite compatibility for testing
- Database-level idle timeouts to prevent stuck processes
- MS SQL Server support

## Basic Usage

```python
from ansible_base.lib.utils.db import advisory_lock


def my_task():
    with advisory_lock('my_task_lock', wait=False) as held:
        if held is False:
            return
        # continue to run logic in my_task
```

This ensures that no other process *in the cluster* connected to the same database instance runs `my_task` at the same time.

The specific choice of `wait=False` and what to do when another task holds the lock is the choice of the programmer in the specific case. In this example, the `return` would be okay in the situation where `my_task` is idempotent, and there is a "fallback" schedule in case a call was missed.

## API

```python
advisory_lock(
    *args,
    lock_session_timeout_milliseconds=0,
    wait=True,
    shared=False,
    using=None
)
```

### Parameters

- **`*args`**: Lock identifier
  - **PostgreSQL**: Integer, 2-integer tuple, or string
  - **MS SQL Server**: Converted to string resource name (max 255 chars)
    - Integer → `"dab_lock_{n}"`
    - Tuple `(a, b)` → `"dab_lock_{a}_{b}"`
    - String → Truncated to 255 chars if needed
    - Other types → CRC32 hash → `"dab_lock_{hash}"`

- **`lock_session_timeout_milliseconds`** (int, default: 0): Database-level timeout
  - 0 = use database defaults (wait indefinitely if `wait=True`)
  - \>0 = timeout after N milliseconds
  - **PostgreSQL**: Sets `idle_in_transaction_session_timeout` and `idle_session_timeout`
  - **MS SQL Server**: Passed to `sp_getapplock @LockTimeout`

- **`wait`** (bool, default: True): Block until lock acquired?
  - `True`: Block indefinitely (or until timeout)
  - `False`: Return immediately if lock unavailable

- **`shared`** (bool, default: False): Lock mode
  - `False`: Exclusive lock (no other locks allowed)
  - `True`: Shared lock (other shared locks allowed)

- **`using`** (str, optional): Django database alias (default: `'default'`)

### Returns

Context manager that yields:
- **`True`**: Lock acquired
- **`False`**: Lock not acquired (only when `wait=False`)

### Raises

- **`RuntimeError`**: Unsupported database vendor
- **`OperationalError`**: Lock operation failed (timeout, deadlock, etc.)

## Implementation Details

### PostgreSQL

- Uses `pg_advisory_lock()` and `pg_try_advisory_lock()` from django-pglocks
- Lock IDs are integers or 2-integer tuples passed directly to the database
- **Session-scoped by default** - locks persist until explicitly released or session ends
- Supports both exclusive and shared lock modes
- Timeout handled via `idle_in_transaction_session_timeout` and `idle_session_timeout` settings
- **Connection recovery**: On timeout, the connection is closed (`close_if_unusable_or_obsolete()`) as timeout leaves it in an unusable state

### MS SQL Server

- Uses `sp_getapplock` stored procedure
- **Lock IDs must be strings** (resource names, max 255 chars) - automatic conversion applied
- Uses `LockOwner='Session'` explicitly (not `Transaction`, which requires an active transaction)
- Return codes:
  - `0` = Lock granted immediately
  - `1` = Lock granted after waiting
  - `-1` = Timeout
  - `-2` = Canceled
  - `-3` = Deadlock victim
  - `-999` = Parameter validation or other error
- **Must explicitly release** with `sp_releaseapplock` (handled in `finally` block)
- **Connection recovery**: On error, connection is closed

### SQLite

- No-op implementation (no distributed locking needed for single-process database)
- Always yields `True`

## Key Behavioral Differences

| Aspect | PostgreSQL | MS SQL Server |
|--------|-----------|---------------|
| **Lock ID format** | Native integers or 2-integer tuples | Strings (auto-converted from int/tuple) |
| **Max lock ID size** | 2 integers (64-bit each) | 255 characters |
| **Release mechanism** | Auto-releases on transaction/session end | Explicit `sp_releaseapplock` required |
| **Scope** | Session or transaction | Session (explicit `LockOwner='Session'`) |
| **Error codes** | Generic `OperationalError` | Distinct codes for timeout/deadlock/cancel |
| **Timeout handling** | Set via session variables | Passed to `sp_getapplock` parameter |
| **Connection recovery** | Closes on timeout | Closes on any error |

## Examples

### Non-blocking lock with status check

```python
with advisory_lock('import_task', wait=False) as acquired:
    if not acquired:
        logger.info('Import task already running, skipping')
        return
    
    # Run import
    run_import()
```

### Shared lock with timeout

```python
with advisory_lock(
    'read_config',
    shared=True,
    lock_session_timeout_milliseconds=5000
) as acquired:
    if acquired:
        # Read configuration
        config = load_config()
    else:
        # Timeout - use cached config
        config = get_cached_config()
```

### Tuple lock ID for namespacing

```python
# Lock specific to organization and resource type
org_id = 42
resource_type = 1

with advisory_lock((org_id, resource_type)):
    # Critical section for this org/resource combination
    process_organization_resource(org_id, resource_type)
```

### Different databases

```python
# Use specific database connection
with advisory_lock('replica_sync', using='replica_db') as acquired:
    if acquired:
        sync_replica()
```

## Production Considerations

### Lock Identifier Design

- Use descriptive names that indicate the protected resource
- For PostgreSQL, prefer integers or tuples for efficiency
- For cross-database compatibility, use integers or 2-integer tuples (not strings)
- Namespace locks by resource type to avoid collisions: `(resource_type_id, object_id)`

### Timeout Configuration

- **Default behavior** (`lock_session_timeout_milliseconds=0`): Wait indefinitely
- **For interactive operations**: Set reasonable timeout (5-30 seconds)
- **For background jobs**: Use `wait=False` or longer timeouts
- **Critical sections**: Keep locks held for minimal duration

### Error Handling

Both PostgreSQL and MS SQL Server will close the database connection on lock operation errors. This is intentional to prevent connection pool pollution with unusable connections.

```python
try:
    with advisory_lock('critical_task', lock_session_timeout_milliseconds=30000) as acquired:
        if acquired:
            perform_critical_task()
except OperationalError as e:
    # Connection was closed - this is expected on timeout/deadlock
    logger.error(f'Lock operation failed: {e}')
    # Django will create a new connection on next database access
```

### Deadlock Prevention

- Acquire locks in consistent order across processes
- Keep critical sections short
- Use timeouts to detect and recover from deadlocks
- Monitor for `-3` (deadlock victim) errors on MS SQL Server

### Testing

Advisory locks are no-ops on SQLite, so:
- Unit tests using SQLite will not exercise lock contention
- For testing lock behavior, use PostgreSQL or MS SQL Server test database
- Mock `advisory_lock` in tests where lock behavior is not the focus

## Common Patterns

### Idempotent Task Execution

```python
def periodic_cleanup():
    """Run cleanup, but skip if already running."""
    with advisory_lock('periodic_cleanup', wait=False) as held:
        if not held:
            return  # Another process is running cleanup
        
        # Perform cleanup
        delete_old_records()
```

### Exclusive Resource Modification

```python
def update_shared_config(new_config):
    """Ensure only one process updates config at a time."""
    with advisory_lock('shared_config'):
        # Exclusive lock - all other processes wait
        current = load_config()
        merged = merge_config(current, new_config)
        save_config(merged)
```

### Read-Write Coordination

```python
# Writer (exclusive)
def write_data(data):
    with advisory_lock('data_lock', shared=False):
        save_data(data)

# Readers (shared)
def read_data():
    with advisory_lock('data_lock', shared=True):
        return load_data()
```

## Migration Notes

If migrating from django-pglocks:

1. Replace `from django_pglocks import advisory_lock` with `from ansible_base.lib.utils.db import advisory_lock`
2. No API changes required - the contract is identical
3. Code now works on MS SQL Server and SQLite in addition to PostgreSQL
4. Lock ID conversion happens automatically for MS SQL Server

## See Also

- [django-pglocks documentation](https://pypi.org/project/django-pglocks/)
- [PostgreSQL Advisory Locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)
- [MS SQL Server sp_getapplock](https://learn.microsoft.com/en-us/sql/relational-databases/system-stored-procedures/sp-getapplock-transact-sql)
