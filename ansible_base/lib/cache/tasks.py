from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from django.core.cache import cache

logger = logging.getLogger('ansible_base.lib.cache.tasks')


def clear_cache(
    cache_keys: list[str],
    dependent_keys_resolver: Callable[[str], Iterable[str]] | None = None,
    post_invalidation_hook: Callable[[set[str]], None] | None = None,
) -> None:
    """Clear the specified keys from the Django cache backend.

    This is a plain utility function, not a dispatcherd task. Each consuming
    service wraps it with its own @task(queue='...') decorator to broadcast
    cache invalidation across cluster nodes.

    Args:
        cache_keys: List of cache key strings to invalidate.
        dependent_keys_resolver: Optional callable (key -> iterable[key]) that
            returns additional keys to invalidate for a given key.
        post_invalidation_hook: Optional callable (set[key] -> None) invoked
            after cache deletion with the full set of invalidated keys.
    """
    logger.info("clear_cache called for %d key(s)", len(cache_keys))
    logger.debug("clear_cache key payload: %s", cache_keys)

    all_keys = list(cache_keys)
    if dependent_keys_resolver:
        orig_len = len(all_keys)
        for i in range(orig_len):
            try:
                for dep_key in dependent_keys_resolver(all_keys[i]):
                    all_keys.append(dep_key)
            except Exception:
                logger.exception("dependent_keys_resolver failed for key %r", all_keys[i])

    unique_keys = set(all_keys)
    logger.debug("Invalidating %d cache key(s) via delete_many: %r", len(unique_keys), unique_keys)
    cache.delete_many(unique_keys)

    if post_invalidation_hook:
        try:
            post_invalidation_hook(unique_keys)
        except Exception:
            logger.exception("post_invalidation_hook failed after invalidating keys %r", unique_keys)
