from unittest.mock import MagicMock, patch

import pytest

from ansible_base.lib.cache.tasks import clear_cache


@pytest.fixture
def populated_cache(settings):
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'test-cache-tasks'}}
    from django.core.cache import cache

    cache.clear()
    cache.set('key_a', 'value_a')
    cache.set('key_b', 'value_b')
    cache.set('key_c', 'value_c')
    cache.set('key_d', 'value_d')
    yield cache
    cache.clear()


def test_clear_cache_deletes_specified_keys(populated_cache):
    clear_cache(['key_a', 'key_b'])

    assert populated_cache.get('key_a') is None
    assert populated_cache.get('key_b') is None
    assert populated_cache.get('key_c') == 'value_c'
    assert populated_cache.get('key_d') == 'value_d'


def test_clear_cache_with_dependent_keys_resolver(populated_cache):
    def resolver(key):
        if key == 'key_a':
            return ['key_b', 'key_c']
        return []

    clear_cache(['key_a'], dependent_keys_resolver=resolver)

    assert populated_cache.get('key_a') is None
    assert populated_cache.get('key_b') is None
    assert populated_cache.get('key_c') is None
    assert populated_cache.get('key_d') == 'value_d'


def test_clear_cache_with_post_invalidation_hook(populated_cache):
    hook = MagicMock()

    clear_cache(['key_a', 'key_b'], post_invalidation_hook=hook)

    hook.assert_called_once()
    assert hook.call_args[0][0] == {'key_a', 'key_b'}


def test_clear_cache_hook_receives_expanded_keys(populated_cache):
    def resolver(key):
        if key == 'key_a':
            return ['key_b']
        return []

    hook = MagicMock()

    clear_cache(['key_a'], dependent_keys_resolver=resolver, post_invalidation_hook=hook)

    hook.assert_called_once()
    assert hook.call_args[0][0] == {'key_a', 'key_b'}


def test_clear_cache_empty_key_list(populated_cache):
    clear_cache([])

    assert populated_cache.get('key_a') == 'value_a'
    assert populated_cache.get('key_b') == 'value_b'


def test_clear_cache_deduplicates_keys(populated_cache):
    def resolver(key):
        return ['key_b']

    with patch('ansible_base.lib.cache.tasks.cache') as mock_cache:
        clear_cache(['key_a', 'key_b'], dependent_keys_resolver=resolver)

        mock_cache.delete_many.assert_called_once()
        deleted_keys = mock_cache.delete_many.call_args[0][0]
        assert deleted_keys == {'key_a', 'key_b'}


def test_clear_cache_no_hook_no_resolver(populated_cache):
    clear_cache(['key_a'])

    assert populated_cache.get('key_a') is None
    assert populated_cache.get('key_b') == 'value_b'


def test_clear_cache_resolver_failure_still_invalidates_original_keys(populated_cache):
    def bad_resolver(key):
        if key == 'key_b':
            raise ValueError("bad key")
        return ['key_c']

    clear_cache(['key_a', 'key_b'], dependent_keys_resolver=bad_resolver)

    assert populated_cache.get('key_a') is None
    assert populated_cache.get('key_b') is None
    assert populated_cache.get('key_c') is None
    assert populated_cache.get('key_d') == 'value_d'


def test_clear_cache_hook_failure_does_not_undo_deletion(populated_cache):
    def exploding_hook(keys):
        raise RuntimeError("hook failed")

    clear_cache(['key_a', 'key_b'], post_invalidation_hook=exploding_hook)

    assert populated_cache.get('key_a') is None
    assert populated_cache.get('key_b') is None
