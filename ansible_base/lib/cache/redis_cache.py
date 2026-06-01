import functools
import socket

from django.conf import settings
from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.redis import RedisCache
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

# socket.timeout is redundant (alias for TimeoutError since Python 3.3) but kept for parity with the AWX original.
IGNORED_EXCEPTIONS = (TimeoutError, ResponseError, ConnectionError, socket.timeout)

CONNECTION_INTERRUPTED_SENTINEL = object()


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
    """

    @optionally_ignore_exceptions
    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        return super().add(key, value, timeout, version)

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
        return super().set(key, value, timeout, version)

    @optionally_ignore_exceptions
    def touch(self, key, timeout=DEFAULT_TIMEOUT, version=None):
        return super().touch(key, timeout, version)

    @optionally_ignore_exceptions
    def delete(self, key, version=None):
        return super().delete(key, version)

    @optionally_ignore_exceptions(return_value={})
    def get_many(self, keys, version=None):
        return super().get_many(keys, version)

    @optionally_ignore_exceptions
    def has_key(self, key, version=None):
        return super().has_key(key, version)

    @optionally_ignore_exceptions
    def incr(self, key, delta=1, version=None):
        return super().incr(key, delta, version)

    @optionally_ignore_exceptions
    def set_many(self, data, timeout=DEFAULT_TIMEOUT, version=None):
        return super().set_many(data, timeout, version)

    @optionally_ignore_exceptions
    def delete_many(self, keys, version=None):
        return super().delete_many(keys, version)

    @optionally_ignore_exceptions
    def clear(self):
        return super().clear()
