## Cache Invalidation

Django-ansible-base provides a shared cache invalidation utility that AAP
services use to clear cache keys across cluster nodes. Each service wraps
the utility with its own dispatcherd `@task` decorator to broadcast
invalidation over the appropriate queue.

### Core Utility

```python
from ansible_base.lib.cache.tasks import clear_cache

clear_cache(
    cache_keys,
    dependent_keys_resolver=None,
    post_invalidation_hook=None,
)
```

**Parameters:**

- `cache_keys` — list of cache key strings to invalidate
- `dependent_keys_resolver` — optional callable `(key) -> iterable[key]` that
  returns additional keys to invalidate for a given key (e.g., settings that
  depend on the changed setting)
- `post_invalidation_hook` — optional callable `(set[key]) -> None` invoked
  after cache deletion with the full set of invalidated keys

The function resolves dependent keys, deduplicates, calls
`cache.delete_many()`, and then invokes the post-invalidation hook.

### Usage Pattern

Each service creates a thin wrapper that decorates `clear_cache` as a
dispatcherd broadcast task:

```python
from dispatcherd.publish import task
from ansible_base.lib.cache.tasks import clear_cache

@task(queue='my_service_broadcast', timeout=600)
def clear_my_cache(cache_keys):
    clear_cache(cache_keys)
```

To trigger invalidation after a database change (e.g., from a view or signal
handler), use Django's `connection.on_commit` to ensure the task fires only
after the transaction commits:

```python
from django.db import connection

def perform_update(self, serializer):
    # ... save changes ...
    if changed_keys:
        connection.on_commit(
            lambda: clear_my_cache.delay(changed_keys)
        )
```

### Dependent Key Resolution

When a setting change should cascade to other settings, pass a resolver:

```python
@task(queue='my_service_broadcast', timeout=600)
def clear_setting_cache(setting_keys):
    def resolve(key):
        return settings_registry.get_dependent_settings(key)

    clear_cache(setting_keys, dependent_keys_resolver=resolve)
```

The resolver is called for each key in the original list. Returned keys are
added to the invalidation set and deduplicated before deletion.

### Post-Invalidation Hooks

To perform side effects after cache invalidation (e.g., reconfiguring a
logging handler), pass a hook:

```python
def _post_invalidation(invalidated_keys):
    if 'LOG_LEVEL' in invalidated_keys:
        reconfigure_logging()

clear_cache(keys, post_invalidation_hook=_post_invalidation)
```

The hook receives the full set of invalidated keys (including resolved
dependents).

---

## Auto-Sync Cache Driver

DAB provides `DABRedisCache`, a cache backend that automatically broadcasts
cache invalidation to other cluster nodes via dispatcherd when cache write
operations occur. This implements the "G3" pattern from the platform caching
strategy — dispatcherd sync is transparent to application code.

### How It Works

When `ANSIBLE_BASE_REDIS_AUTO_INVALIDATE` is `True`, the `add`, `set`, and
`delete` methods on `DABRedisCache` automatically publish a dispatcherd task
after the local cache write succeeds. On each receiving node, the task calls
`clear_cache()` to delete the specified keys from that node's local sidecar
Redis.

**Note:** Bulk operations (`set_many`, `delete_many`, `clear`) do not trigger
broadcasts. Use individual `set`/`delete` calls when cross-node invalidation
is required. The raw cache key name is broadcast without a `version` parameter;
all nodes must share the same `KEY_PREFIX` and `VERSION` in their CACHES
configuration for invalidation to target the correct key.

### Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `ANSIBLE_BASE_REDIS_AUTO_INVALIDATE` | bool | `False` | Enable automatic cache invalidation broadcasting on write operations |
| `ANSIBLE_BASE_CACHE_BROADCAST_QUEUE` | str | `'broadcast'` | Dispatcherd queue name for fan-out to all nodes |
| `CLUSTER_HOST_ID` | str | — | Unique node identifier; required for the self-invalidation guard. If unset, a warning is logged and the originating node will also clear its own cache after broadcasting. |

### Consumer Setup

To enable auto-sync in a consuming service:

1. **Use `DABRedisCache` as the CACHES backend:**

```python
CACHES = {
    "default": {
        "BACKEND": "ansible_base.lib.cache.redis_cache.DABRedisCache",
        "LOCATION": "unix:///var/run/redis/redis.sock",
    },
}
```

2. **Set the auto-invalidation settings:**

```python
ANSIBLE_BASE_REDIS_AUTO_INVALIDATE = True
ANSIBLE_BASE_CACHE_BROADCAST_QUEUE = 'my_service_broadcast'
```

3. **Ensure dispatcherd is running** with a matching broadcast channel in
   its configuration. For example, Gateway uses `gateway_broadcast`.

4. **`dispatcherd` must be installed** as a dependency of the consuming
   service. It is not a DAB dependency — if the package is absent,
   `DABRedisCache` logs a warning and operates without broadcasting.

### Self-Invalidation Guard

When a node writes to its local sidecar Redis and broadcasts invalidation,
the broadcast reaches ALL nodes — including the originator. Without
protection, the originator would immediately delete the value it just set.

This is particularly harmful for expensive cache entries like JWT tokens
(60ms–4000ms to create). To prevent this, each broadcast includes the
originating node's `CLUSTER_HOST_ID`. The receiving task skips cache
clearing when the origin matches the local node.

### Re-Entrancy Protection

The receiving side calls `clear_cache()` → `cache.delete_many()` →
`DABRedisCache.delete_many()`. Without protection, `delete_many` could
trigger another broadcast, creating an infinite loop.

A thread-local guard (`_broadcast_guard`) prevents this: when a broadcast
handler is already running, subsequent write operations on the same thread
skip the broadcast step.
