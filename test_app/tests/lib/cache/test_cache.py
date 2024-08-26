import time

from django.core.cache.backends.base import BaseCache
from django.test import override_settings

from ansible_base.lib.cache.fallback_cache import CACHE_STATUS_KEY, FALLBACK_CACHE, PRIMARY_CACHE, RECOVERY_KEY, DABCacheWithFallback


class BreakableCache(BaseCache):
    def __init__(self, location, params):
        self.cache = {}
        self.working = True

    def add(self, key, value, timeout=300, version=None):
        self.cache[key] = value

    def get(self, key, default=None, version=None):
        if self.working:
            return self.cache.get(key, default)
        else:
            raise RuntimeError("Sorry, cache no worky")

    def set(self, key, value, timeout=300, version=None, client=None):
        self.cache[key] = value

    def delete(self, key, version=None):
        self.cache.pop(key, None)

    def clear(self):
        self.cache = {}

    def breakit(self):
        self.working = False

    def fixit(self):
        self.working = True


def test_fallback_cache():
    caches = {
        'default': {
            'BACKEND': 'ansible_base.lib.cache.fallback_cache.DABCacheWithFallback',
        },
        'primary': {
            'BACKEND': 'test_app.tests.lib.cache.test_cache.BreakableCache',
            'LOCATION': 'primary',
            'OPTIONS': {
                'recovery_check_freq_sec': 1,
            },
        },
        'fallback': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'fallback',
        },
        'fallback_status': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'fallback_status',
        },
    }

    with override_settings(CACHES=caches):
        cache = DABCacheWithFallback("", {})

    primary = cache._primary_cache
    fallback = cache._fallback_cache
    status = cache._status_cache

    cache.set('key', 'val1')
    assert primary.get('key') == 'val1'
    assert fallback.get('key') is None
    assert status.get(CACHE_STATUS_KEY) == PRIMARY_CACHE

    primary.set('tobecleared', True)
    primary.breakit()

    # Breaks primary
    cache.get('key')

    assert status.get(CACHE_STATUS_KEY) == FALLBACK_CACHE
    assert status.get(RECOVERY_KEY)

    # Sets in fallback
    cache.set('key', 'val2')

    assert cache.get('key', 'val2')

    primary.fixit()

    time.sleep(10)
    assert status.get(CACHE_STATUS_KEY) == PRIMARY_CACHE
    assert not status.get(RECOVERY_KEY)

    assert cache.get('key') is None
    assert fallback.get('key') == 'val2'

    # Ensure primary was cleared
    assert not cache.get('tobecleared', False)

    cache.set('key2', 'val3')

    assert cache.get('key2') == 'val3'
