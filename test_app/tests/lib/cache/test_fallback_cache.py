import logging
import time

from django.core import cache as django_cache
from django.core.cache.backends.base import BaseCache
from django.test import override_settings

from ansible_base.lib.cache.fallback_cache import FALLBACK_CACHE, PRIMARY_CACHE


class BreakableCache(BaseCache):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(BreakableCache, cls).__new__(cls)
            cls.__initialized = False
        return cls._instance

    def __init__(self, location, params):
        if self.__initialized:
            return
        self.cache = {}
        options = params.get("OPTIONS", {})
        self.working = options.get("working", True)
        self.__initialized = True

    def add(self, key, value, timeout=300, version=None):
        self.cache[key] = value

    def get(self, key, default=None, version=None):
        if self.working:
            return self.cache.get(key, default)
        else:
            raise RuntimeError(f"Sorry, cache no worky {self}")

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


cache_settings = {
    'default': {
        'BACKEND': 'ansible_base.lib.cache.fallback_cache.DABCacheWithFallback',
    },
    'primary': {
        'BACKEND': 'test_app.tests.lib.cache.test_fallback_cache.BreakableCache',
        'LOCATION': 'primary',
    },
    'fallback': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'fallback',
    },
}


@override_settings(CACHES=cache_settings)
def test_fallback_cache():
    cache = django_cache.caches.create_connection('default')

    primary = cache._primary_cache
    fallback = cache._fallback_cache
    cache.set('key', 'val1')
    assert primary.get('key') == 'val1'
    assert fallback.get('key') is None

    primary.set('tobecleared', True)
    primary.breakit()

    # Breaks primary
    cache.get('key')

    # Sets in fallback
    cache.set('key', 'val2')

    assert cache.get('key', 'val2')

    assert cache.get_active_cache() == FALLBACK_CACHE

    primary.fixit()

    # Check until primary is back
    timeout = time.time() + 30
    while True:
        if cache.get_active_cache() == PRIMARY_CACHE:
            break
        if time.time() > timeout:
            assert False
        time.sleep(1)

    # Ensure caches were cleared
    assert cache.get('key') is None
    assert fallback.get('key') is None
    assert cache.get('tobecleared') is None

    cache.set('key2', 'val3')

    assert cache.get('key2') == 'val3'


@override_settings(CACHES=cache_settings)
def test_dead_primary():
    primary_cache = django_cache.caches.create_connection('primary')
    primary_cache.breakit()

    # Kill post-shutdown logging from unfinished recovery checker
    logging.getLogger('ansible_base.cache.fallback_cache').setLevel(logging.CRITICAL)

    cache = django_cache.caches.create_connection('default')

    cache.set('key', 'val')
    cache.get('key')

    # Check until fallback is set
    timeout = time.time() + 30
    while True:
        if cache.get_active_cache() == FALLBACK_CACHE:
            break
        if time.time() > timeout:
            assert False
        time.sleep(1)
