import logging
import multiprocessing
import time
from threading import Thread

from django.core import cache as django_cache
from django.core.cache.backends.base import BaseCache

logger = logging.getLogger('ansible_base.cache.fallback_cache')

DEFAULT_TIMEOUT = None
PRIMARY_CACHE = 'primary'
FALLBACK_CACHE = 'fallback'
STATUS_CACHE = 'fallback_status'
CACHE_STATUS_KEY = 'fallback_status_indicator'
RECOVERY_KEY = 'recovery_in_progress'
RECOVERY_CHECK_FREQ_SEC = 10


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

        options = params.get("OPTIONS", {})
        self._recovery_check_freq_sec = options.get("recovery_check_freq_sec", RECOVERY_CHECK_FREQ_SEC)
        # Default to primary
        self._status_cache.set(CACHE_STATUS_KEY, PRIMARY_CACHE)
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
                with multiprocessing.Lock():
                    if not self._status_cache.get(RECOVERY_KEY, default=False):
                        logger.error("Primary cache unavailable, switching to fallback cache.")
                        self._status_cache.set(RECOVERY_KEY, True)
                        self._status_cache.set(CACHE_STATUS_KEY, FALLBACK_CACHE)
                        RecoveryThread(self._primary_cache, self._status_cache, self._recovery_check_freq_sec).start()
        response = getattr(self._fallback_cache, operation)(*args, **kwargs)
        return response


class RecoveryThread(Thread):
    def __init__(self, primary_cache, status_cache, retry_seconds):
        Thread.__init__(self)
        self.primary_cache = primary_cache
        self.status_cache = status_cache
        self.retry_seconds = retry_seconds

    def run(self):
        while True:
            time.sleep(self.retry_seconds)
            try:
                self.primary_cache.get('317783e3-03f6-4f05-9a22-7c774a0bbea3', default=True)
                logger.warning(f"Primary cache recovered, clearing and resuming use. {self}")
                self.primary_cache.clear()
                self.status_cache.set(CACHE_STATUS_KEY, PRIMARY_CACHE)
                self.status_cache.set(RECOVERY_KEY, False)
                return
            except Exception as e:
                logger.error(f"Primary cache still not available, {self} retrying: {e}")
