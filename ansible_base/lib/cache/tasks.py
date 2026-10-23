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


# --- Auto-sync broadcast task (dispatcherd) ---
#
# This @task-decorated function is the RECEIVING side of the auto-sync pattern.
# When DABRedisCache broadcasts a cache invalidation via dispatcherd, this task
# runs on each cluster node and deletes the specified keys from local cache.
#
# dispatcherd is optional — it is not a DAB dependency. If the package is not
# installed, the task is unavailable and DABRedisCache logs a warning.

try:
    from dispatcherd.publish import task

    def _get_broadcast_queue():
        """Return the dispatcherd broadcast queue name from Django settings.

        Read at call time (not import time) so each consuming service can
        configure its own queue: Gateway uses 'gateway_broadcast',
        AWX uses 'tower_broadcast_all'.
        """
        from django.conf import settings

        return getattr(settings, 'ANSIBLE_BASE_CACHE_BROADCAST_QUEUE', 'broadcast')

    @task(queue=_get_broadcast_queue)
    def broadcast_cache_invalidation(cache_keys, origin_node=None):
        """Delete cache keys on this node, skipping if we are the originator.

        The origin_node parameter implements the self-invalidation guard:
        when a node writes to its local sidecar Redis and broadcasts, the
        broadcast reaches ALL nodes (including the originator). Without this
        guard, the originator would immediately delete the value it just set,
        making the cache useless for expensive operations like JWT creation.

        Note: this calls bare clear_cache() without dependent_keys_resolver or
        post_invalidation_hook. Services that need those (e.g., Gateway's
        clear_gateway_cache) should be able to register their own wrapper.
        See AAP-77769 for follow-up on service wrapper delegation.
        """
        from django.conf import settings

        local_node = getattr(settings, 'CLUSTER_HOST_ID', '')
        if origin_node and origin_node == local_node:
            logger.debug("Skipping self-invalidation for node %s", origin_node)
            return
        clear_cache(cache_keys)

    HAS_DISPATCHERD = True

except ImportError:
    HAS_DISPATCHERD = False
    broadcast_cache_invalidation = None
