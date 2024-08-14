import asyncio
import logging
from django.core.cache.backends.base import BaseCache
from django.core import cache as django_cache

logger = logging.getLogger('ansible_base.cache.fallback_cache')

DEFAULT_TIMEOUT = None
PRIMARY_CACHE = 'primary'
FALLBACK_CACHE = 'fallback'
STATUS_CACHE = 'fallback_status'
CACHE_STATUS_KEY = 'fallback_status_indicator'


class DABCacheWithFallback(BaseCache):
    _instance = None
    _initialized = False
    _primary_cache = None
    _fallback_cache = None
    _status_cache = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(DABCacheWithFallback, cls).__new__(cls)
            cls.__initialized = False
        return cls._instance

    def __init__(self, location, params):
        if self.__initialized:
            return
        BaseCache.__init__(self, params)

        self._primary_cache = django_cache.caches.create_connection(PRIMARY_CACHE)
        self._fallback_cache = django_cache.caches.create_connection(FALLBACK_CACHE)
        self._status_cache = django_cache.caches.create_connection(STATUS_CACHE)

        self.__initialized = True

    # Main cache interface
    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        return self._op_with_fallback("add", key, value, timeout=timeout, version=version)

    def get(self, key, default=None, version=None):
        return self._op_with_fallback("get", key, default=default, version=version)

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None, client=None):
        return self._op_with_fallback("set", key, value, timeout=timeout)

    def delete(self, key, version=None):
        return self._op_with_fallback("delete", key, version=version)

    def clear(self):
        return self._op_with_fallback("clear")

    # Internal
    def _op_with_fallback(self, operation, *args, **kwargs):
        if self._status_cache.get(CACHE_STATUS_KEY, default=PRIMARY_CACHE) == PRIMARY_CACHE:
            try:
                response = getattr(self._primary_cache, operation)(*args, **kwargs)
                return response

            except Exception:
                logger.error("Primary cache unavailable, switching to fallback cache.")
                self._status_cache.set(CACHE_STATUS_KEY, FALLBACK_CACHE)
                asyncio.run(self._recover_primary())
        response = getattr(self._fallback_cache, operation)(*args, **kwargs)
        return response

    async def _recover_primary(self):
        await asyncio.sleep(10)
        try:
            self._primary_cache.get('fakekey')
            logger.warn("Primary cache recovered, clearing and resuming use.")
            self._primary_cache.clear()
            self._status_cache.set(CACHE_STATUS_KEY, PRIMARY_CACHE)
        except Exception:
            logger.error("Primary cache still not available, retrying.")
            await self._recover_primary()
