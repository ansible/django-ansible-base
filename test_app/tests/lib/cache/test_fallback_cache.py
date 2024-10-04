import logging
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest
from django.core import cache as django_cache
from django.core.cache.backends.base import BaseCache
from django.test import override_settings

from ansible_base.lib.cache.fallback_cache import FALLBACK_CACHE, PRIMARY_CACHE, DABCacheWithFallback


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
def test_nonwritable_dir():
    nonwrite = Path().joinpath(tempfile.gettempdir(), "nowrite")
    try:
        nonwrite.rmdir()  # In case it exists already
    except Exception:
        pass
    nonwrite.mkdir()
    nonwrite.chmod(0o400)
    with pytest.raises(Exception):
        DABCacheWithFallback(nonwrite, {})
    nonwrite.rmdir()


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
        # Tell the cache to get a key, this should cause it to check the primary cache
        cache.get("key")
        active_cache = cache.get_active_cache()
        if active_cache == PRIMARY_CACHE:
            break
        if time.time() > timeout:
            assert False
        time.sleep(1)

    # Ensure caches were cleared
    assert cache.get('key') is None
    assert fallback.get('key') is None
    assert cache.get('tobecleared') is None

    assert primary.get('key2') is None
    cache.set('key2', 'val3')
    assert primary.get('key2') == 'val3'
    assert fallback.get('key2') is None


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


@override_settings(CACHES=cache_settings)
def test_ensure_temp_file_is_removed_on_init():
    temp_file = Path(tempfile.NamedTemporaryFile().name)
    with mock.patch.object(DABCacheWithFallback, '_temp_file', temp_file):
        temp_file.touch()
        # Remove singleton instance
        DABCacheWithFallback._instance = None
        DABCacheWithFallback(None, {})
        assert DABCacheWithFallback._temp_file.exists() is False


@override_settings(CACHES=cache_settings)
def test_ensure_initialization_wont_happen_twice():
    with mock.patch('ansible_base.lib.cache.fallback_cache.ThreadPoolExecutor') as tfe:
        # Remove singleton instance
        DABCacheWithFallback._instance = None
        cache = DABCacheWithFallback(None, {})
        tfe.assert_called_once()
        cache.__init__(None, {})
        # when calling init again ThreadPoolExecute should not be called again so we should still have only one call
        tfe.assert_called_once()


@pytest.mark.parametrize(
    "method",
    [
        ('clear'),
        ('delete'),
        ('set'),
        ('get'),
        ('add'),
    ],
)
@override_settings(CACHES=cache_settings)
def test_all_methods_are_overwritten(method):
    with mock.patch('ansible_base.lib.cache.fallback_cache.DABCacheWithFallback._op_with_fallback') as owf:
        cache = DABCacheWithFallback(None, {})
        if method == 'clear':
            getattr(cache, method)()
        elif method in ['delete', 'get']:
            getattr(cache, method)('test_value')
        else:
            getattr(cache, method)('test_value', 1)
        owf.assert_called_once()


@pytest.mark.parametrize(
    "file_exists",
    [
        (True),
        (False),
    ],
)
@override_settings(CACHES=cache_settings)
def test_check_primary_cache(file_exists):
    temp_file = Path(tempfile.NamedTemporaryFile().name)
    with mock.patch.object(DABCacheWithFallback, '_temp_file', temp_file):
        # Remove singleton instance
        DABCacheWithFallback._instance = None
        # Initialization of the cache will clear the temp file so do this first
        cache = DABCacheWithFallback(None, {})
        # Ensure cache is working
        cache._primary_cache.fixit()

        # Create the temp file if needed
        if file_exists:
            temp_file.touch()
            # Set file back after deletion
            DABCacheWithFallback._temp_file = temp_file
        else:
            try:
                temp_file.unlink()
            except Exception:
                pass
        mocked_function = mock.MagicMock(return_value=None)
        cache._primary_cache.clear = mocked_function
        cache.check_primary_cache()
        if file_exists:
            mocked_function.assert_called_once()
        else:
            mocked_function.assert_not_called()
        assert temp_file.exists() is False


@override_settings(CACHES=cache_settings)
def test_file_unlink_exception_does_not_cause_failure():
    temp_file = Path(tempfile.NamedTemporaryFile().name)
    with mock.patch.object(DABCacheWithFallback, '_temp_file', temp_file):
        cache = DABCacheWithFallback(None, {})
        # We can't do: temp_file.unlink = mock.MagicMock(side_effect=Exception('failed to unlink exception'))
        # Because unlink is marked as read only so we will just mock the cache.clear to raise in its place
        mocked_function = mock.MagicMock(side_effect=Exception('failed to delete a file exception'))
        cache._primary_cache.clear = mocked_function

        temp_file.touch()
        cache.check_primary_cache()
        # No assertion needed because we just want to make sure check_primary_cache does not raise
