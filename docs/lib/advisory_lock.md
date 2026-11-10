## Database Named Locks

Django-ansible-base hosts its own specialized utility for obtaining named locks.
This follows the same contract as documented in the django-pglocks library

https://pypi.org/project/django-pglocks/

Due to a multitude of needs relevant to production use, discovered through its
use in AWX, a number of points of divergence have emerged such as:

 - the need to have it not error when running sqlite3 tests
 - stuck processes holding the lock forever (adding pg-level idle timeout)

The use for the purpose of a task would typically look like this

```python
from ansible_base.lib.utils.db import advisory_lock


def my_task():
    with advisory_lock('my_task_lock', wait=False) as held:
        if held is False:
            return
        # continue to run logic in my_task
```

This is very useful to assure that no other process _in the cluster_ connected
to the same postgres instance runs `my_task` at the same time as the process
calling it here.

The specific choice of `wait=False` and what to do when another task holds the lock,
is the choice of the programmer in the specific case.
In this case, the `return` would be okay in the situation where `my_task` is idempotent,
and there is a "fallback" schedule in case a call was missed.
The blocking/non-blocking choices are very dependent on the specific design and situation.

## Debugging Advisory Locks

For debugging purposes, several utility functions are available to inspect active advisory locks:

### Get Active Advisory Locks

```python
from ansible_base.lib.utils.db import get_active_advisory_locks

# Get all active advisory locks
active_locks = get_active_advisory_locks()
for lock in active_locks:
    print(f"Lock ID: {lock['objid']}, PID: {lock['pid']}")
```

### Convert String to Lock ID

```python
from ansible_base.lib.utils.db import string_to_advisory_lock_id

# Convert a string to the corresponding advisory lock ID
lock_id = string_to_advisory_lock_id('my_task_lock')
print(f"Lock ID for 'my_task_lock': {lock_id}")
```

### Convert Lock ID to Debug Info

```python
from ansible_base.lib.utils.db import advisory_lock_id_to_debug_info

# Get debug information for a specific lock ID
debug_info = advisory_lock_id_to_debug_info(lock_id)
print(f"Original string: {debug_info}")
```

These debugging utilities are particularly useful when troubleshooting stuck locks or understanding which processes are holding specific advisory locks in a PostgreSQL database.
