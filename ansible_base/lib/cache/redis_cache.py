import functools
import logging
import socket
import threading

from django.conf import settings
from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.redis import RedisCache
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

logger = logging.getLogger('ansible_base.lib.cache.redis_cache')

# socket.timeout is redundant (alias for TimeoutError since Python 3.3) but kept for parity with the AWX original.
IGNORED_EXCEPTIONS = (TimeoutError, ResponseError, ConnectionError, socket.timeout)

CONNECTION_INTERRUPTED_SENTINEL = object()

# Defense-in-depth re-entrancy guard for future broadcast expansion.
# Today, storm prevention relies on bulk ops (delete_many, set_many, clear) not broadcasting.
# If a future change (AAP-77769) extends broadcasting to those methods, this guard prevents
# infinite loops within the same thread. It does NOT protect against cross-process storms
# (dispatcherd tasks run in separate processes) — that requires a different mechanism.
_broadcast_guard = threading.local()

# Log the missing-dispatcherd warning only once to avoid flooding logs under load.
_dispatcherd_warning_logged = False
_cluster_host_id_warning_logged = False
_cluster_host_id_logged = False


def optionally_ignore_exceptions(func=None, return_value=None):
    if func is None:
        return functools.partial(optionally_ignore_exceptions, return_value=return_value)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except IGNORED_EXCEPTIONS as e:
            if getattr(settings, 'DJANGO_REDIS_IGNORE_EXCEPTIONS', True):
                return return_value
            raise e.__cause__ or e

    return wrapper


class DABRedisCache(RedisCache):
    """
    Wraps Django's RedisCache to optionally ignore exceptions when the cache is unavailable.

    When ANSIBLE_BASE_REDIS_AUTO_INVALIDATE is True, cache write operations (add, set, delete)
    automatically broadcast invalidation to other cluster nodes via dispatcherd. This enables
    sidecar Redis instances to stay in sync without application code needing to call dispatcherd
    explicitly. Requires dispatcherd to be installed and running in the consuming service.

    Settings:
        ANSIBLE_BASE_REDIS_AUTO_INVALIDATE (bool, default False):
            Master switch for automatic cache invalidation broadcasting.
        ANSIBLE_BASE_CACHE_BROADCAST_QUEUE (str, default 'broadcast'):
            The dispatcherd queue name used for fan-out to all nodes.
            Gateway uses 'gateway_broadcast'; AWX uses 'tower_broadcast_all'.
        CLUSTER_HOST_ID (str):
            Unique identifier for this node. Used by the self-invalidation guard
            to skip broadcasts received by the originating node.
    """

    def _should_broadcast(self):
        """Check whether this cache operation should trigger a broadcast.

        Returns False when auto-invalidation is disabled or when we are already
        inside a broadcast handler (re-entrancy guard).
        """
        return getattr(settings, 'ANSIBLE_BASE_REDIS_AUTO_INVALIDATE', False) and not getattr(_broadcast_guard, 'active', False)

    def _broadcast_invalidation(self, keys):
        """Publish a cache invalidation message to all cluster nodes via dispatcherd.

        Includes this node's CLUSTER_HOST_ID as origin_node so the receiving side
        can skip self-invalidation — without this guard, a cache.set() would be
        immediately followed by a delete on the originating node, making the cache
        useless for high-cost operations like JWT creation (60ms-4000ms per P3).

        The _broadcast_guard around apply_async is defense-in-depth for future changes
        (AAP-77769). Today, cross-process storm prevention relies on bulk ops not
        broadcasting — see the comment on _broadcast_guard above.
        """
        global _dispatcherd_warning_logged, _cluster_host_id_warning_logged, _cluster_host_id_logged

        if not self._should_broadcast():
            return

        from ansible_base.lib.cache.tasks import HAS_DISPATCHERD, broadcast_cache_invalidation

        if not HAS_DISPATCHERD or broadcast_cache_invalidation is None:
            if not _dispatcherd_warning_logged:
                logger.warning("ANSIBLE_BASE_REDIS_AUTO_INVALIDATE is True but dispatcherd is not installed")
                _dispatcherd_warning_logged = True
            return

        origin = getattr(settings, 'CLUSTER_HOST_ID', '')
        if not origin and not _cluster_host_id_warning_logged:
            logger.warning("ANSIBLE_BASE_REDIS_AUTO_INVALIDATE is True but CLUSTER_HOST_ID is not set; self-invalidation guard will be ineffective")
            _cluster_host_id_warning_logged = True
        elif origin and not _cluster_host_id_logged:
            logger.info("DABRedisCache auto-sync broadcasting as node %r", origin)
            _cluster_host_id_logged = True

        _broadcast_guard.active = True
        try:
            broadcast_cache_invalidation.apply_async(
                args=[list(keys)],
                kwargs={'origin_node': origin},
            )
        except Exception:
            logger.exception("Failed to broadcast cache invalidation for keys %r", keys)
        finally:
            _broadcast_guard.active = False

    @optionally_ignore_exceptions
    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        result = super().add(key, value, timeout, version)
        # Only broadcast when the key was actually added (result is True).
        # When the key already exists, add() returns False and no write occurred.
        if result:
            self._broadcast_invalidation([key])
        return result

    @optionally_ignore_exceptions(return_value=CONNECTION_INTERRUPTED_SENTINEL)
    def _get(self, key, default=None, version=None):
        return super().get(key, default, version)

    def get(self, key, default=None, version=None):
        value = self._get(key, default, version)
        if value is CONNECTION_INTERRUPTED_SENTINEL:
            return default
        return value

    @optionally_ignore_exceptions
    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        result = super().set(key, value, timeout, version)
        self._broadcast_invalidation([key])
        return result

    @optionally_ignore_exceptions
    def touch(self, key, timeout=DEFAULT_TIMEOUT, version=None):
        return super().touch(key, timeout, version)

    @optionally_ignore_exceptions
    def delete(self, key, version=None):
        result = super().delete(key, version)
        self._broadcast_invalidation([key])
        return result

    @optionally_ignore_exceptions(return_value={})
    def get_many(self, keys, version=None):
        return super().get_many(keys, version)

    @optionally_ignore_exceptions
    def has_key(self, key, version=None):
        return super().has_key(key, version)

    @optionally_ignore_exceptions
    def incr(self, key, delta=1, version=None):
        return super().incr(key, delta, version)

    # Bulk write operations (set_many, delete_many, clear) and other mutations (touch, incr)
    # intentionally do NOT broadcast. AAP-65921 scopes auto-sync to add, set, delete.
    # Extending to all mutations requires decoupling storm prevention first — the receiving
    # side calls clear_cache() -> cache.delete_many(), and if delete_many also broadcasts
    # it creates a cross-process infinite loop. See AAP-77769 for follow-up.

    @optionally_ignore_exceptions
    def set_many(self, data, timeout=DEFAULT_TIMEOUT, version=None):
        return super().set_many(data, timeout, version)

    @optionally_ignore_exceptions
    def delete_many(self, keys, version=None):
        return super().delete_many(keys, version)

    @optionally_ignore_exceptions
    def clear(self):
        return super().clear()
