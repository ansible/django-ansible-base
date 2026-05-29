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
