import logging
import multiprocessing
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.core import cache as django_cache
from django.core.cache.backends.base import BaseCache

logger = logging.getLogger('ansible_base.cache.fallback_cache')

DEFAULT_TIMEOUT = None
PRIMARY_CACHE = 'primary'
FALLBACK_CACHE = 'fallback'

_temp_file = Path().joinpath(tempfile.gettempdir(), 'gw_primary_cache_failed')


class DABCacheWithFallback(BaseCache):
    _instance = None
    _primary_cache = None
    _fallback_cache = None

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
        self.thread_pool = ThreadPoolExecutor()

        if _temp_file.exists():
            _temp_file.unlink()

        self.__initialized = True

    def get_active_cache(self):
        return FALLBACK_CACHE if _temp_file.exists() else PRIMARY_CACHE

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

    def _op_with_fallback(self, operation, *args, **kwargs):
        if _temp_file.exists():
            response = getattr(self._fallback_cache, operation)(*args, **kwargs)
            self.thread_pool.submit(DABCacheWithFallback.check_primary_cache)
        else:
            try:
                response = getattr(self._primary_cache, operation)(*args, **kwargs)
                return response
            except Exception:
                with multiprocessing.Lock():
                    if not _temp_file.exists():
                        logger.error("Primary cache unavailable, switching to fallback cache.")
                    _temp_file.touch()
                response = getattr(self._fallback_cache, operation)(*args, **kwargs)

        return response

    @staticmethod
    def check_primary_cache():
        try:
            primary_cache = django_cache.caches.create_connection(PRIMARY_CACHE)
            primary_cache.get('up_test')
            with multiprocessing.Lock():
                if _temp_file.exists():
                    logger.warning("Primary cache recovered, clearing and resuming use.")
                    # Clear the primary cache
                    primary_cache.clear()
                    # Clear the backup cache just incase we need to fall back again (don't want it out of sync)
                    fallback_cache = django_cache.caches.create_connection(FALLBACK_CACHE)
                    fallback_cache.clear()
                    _temp_file.unlink()
        except Exception:
            pass
