import importlib
import sys
from unittest import mock

import pytest
from django.core.cache.backends.redis import RedisCache
from django.test import override_settings
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from ansible_base.lib.cache.redis_cache import CONNECTION_INTERRUPTED_SENTINEL, DABRedisCache, _broadcast_guard, optionally_ignore_exceptions


def test_dab_redis_cache_inherits_redis_cache():
    assert issubclass(DABRedisCache, RedisCache)


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True)
@pytest.mark.parametrize("exc_class", [ConnectionError, TimeoutError, ResponseError])
def test_ignores_exceptions_when_enabled(exc_class):
    @optionally_ignore_exceptions
    def failing():
        raise exc_class("redis down")

    assert failing() is None


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=False)
@pytest.mark.parametrize("exc_class", [ConnectionError, TimeoutError, ResponseError])
def test_raises_exceptions_when_disabled(exc_class):
    @optionally_ignore_exceptions
    def failing():
        raise exc_class("redis down")

    with pytest.raises(exc_class):
        failing()


def test_defaults_to_ignore_when_setting_absent(settings):
    if hasattr(settings, 'DJANGO_REDIS_IGNORE_EXCEPTIONS'):
        delattr(settings, 'DJANGO_REDIS_IGNORE_EXCEPTIONS')

    @optionally_ignore_exceptions
    def failing():
        raise ConnectionError("redis down")

    assert failing() is None


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True)
def test_custom_return_value():
    sentinel = object()

    @optionally_ignore_exceptions(return_value=sentinel)
    def failing():
        raise ConnectionError("redis down")

    assert failing() is sentinel


def _make_cache():
    # Skip __init__ to avoid requiring a live Redis connection for unit tests.
    return DABRedisCache.__new__(DABRedisCache)


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True)
def test_get_returns_default_on_connection_error():
    cache = _make_cache()
    my_default = object()
    with mock.patch.object(RedisCache, 'get', side_effect=ConnectionError("redis down")):
        result = cache.get("some_key", default=my_default)
    assert result is my_default


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True)
def test_get_returns_none_when_no_default():
    cache = _make_cache()
    with mock.patch.object(RedisCache, 'get', side_effect=ConnectionError("redis down")):
        result = cache.get("some_key")
    assert result is None


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True)
def test_get_does_not_return_sentinel():
    cache = _make_cache()
    with mock.patch.object(RedisCache, 'get', side_effect=ConnectionError("redis down")):
        result = cache.get("some_key", default="fallback")
    assert result is not CONNECTION_INTERRUPTED_SENTINEL
    assert result == "fallback"


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True)
@pytest.mark.parametrize(
    "method_name, args",
    [
        ("add", ("key", "value")),
        ("set", ("key", "value")),
        ("touch", ("key",)),
        ("delete", ("key",)),
        ("has_key", ("key",)),
        ("incr", ("key",)),
        ("set_many", ({"key": "value"},)),
        ("delete_many", (["key1", "key2"],)),
        ("clear", ()),
    ],
)
def test_method_handles_connection_error(method_name, args):
    cache = _make_cache()
    with mock.patch.object(RedisCache, method_name, side_effect=ConnectionError("redis down")):
        result = getattr(cache, method_name)(*args)
    assert result is None


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True)
def test_get_many_returns_empty_dict_on_connection_error():
    cache = _make_cache()
    with mock.patch.object(RedisCache, 'get_many', side_effect=ConnectionError("redis down")):
        result = cache.get_many(["key1", "key2"])
    assert result == {}


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=False)
@pytest.mark.parametrize(
    "method_name, args",
    [
        ("add", ("key", "value")),
        ("get", ("key",)),
        ("set", ("key", "value")),
        ("touch", ("key",)),
        ("delete", ("key",)),
        ("get_many", (["key1", "key2"],)),
        ("has_key", ("key",)),
        ("incr", ("key",)),
        ("set_many", ({"key": "value"},)),
        ("delete_many", (["key1", "key2"],)),
        ("clear", ()),
    ],
)
def test_method_raises_when_disabled(method_name, args):
    cache = _make_cache()
    with mock.patch.object(RedisCache, method_name, side_effect=ConnectionError("redis down")):
        with pytest.raises(ConnectionError):
            getattr(cache, method_name)(*args)


# ---------------------------------------------------------------------------
# Auto-sync broadcast tests (ANSIBLE_BASE_REDIS_AUTO_INVALIDATE)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def _reset_broadcast_guard():
    """Ensure the re-entrancy guard is reset between tests."""
    _broadcast_guard.active = False
    yield
    _broadcast_guard.active = False


@pytest.fixture()
def mock_dispatcherd():
    """Mock the dispatcherd package and reload tasks.py so the try block succeeds.

    This allows testing broadcast_cache_invalidation and _get_broadcast_queue
    even when dispatcherd is not installed. The @task decorator is replaced with
    a minimal stub that adds .apply_async and .delay as MagicMocks.
    """
    import ansible_base.lib.cache.tasks as tasks_module

    def fake_task(**kwargs):
        def decorator(fn):
            fn.apply_async = mock.MagicMock()
            fn.delay = mock.MagicMock()
            return fn

        return decorator

    mock_publish = mock.MagicMock()
    mock_publish.task = fake_task

    saved = {}
    for mod_name in ('dispatcherd', 'dispatcherd.publish'):
        saved[mod_name] = sys.modules.get(mod_name)

    sys.modules['dispatcherd'] = mock.MagicMock()
    sys.modules['dispatcherd.publish'] = mock_publish

    importlib.reload(tasks_module)

    yield tasks_module

    for mod_name, original in saved.items():
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original

    importlib.reload(tasks_module)


def test_auto_invalidate_disabled_by_default(_reset_broadcast_guard):
    """No broadcast should occur when ANSIBLE_BASE_REDIS_AUTO_INVALIDATE is not set (defaults to False)."""
    cache = _make_cache()
    mock_task = mock.MagicMock()
    with (
        mock.patch.object(RedisCache, 'set', return_value=None),
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        cache.set("key", "value")
    mock_task.apply_async.assert_not_called()


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
@pytest.mark.parametrize(
    "method_name, args, expected_keys",
    [
        ("set", ("mykey", "value"), ["mykey"]),
        ("add", ("mykey", "value"), ["mykey"]),
        ("delete", ("mykey",), ["mykey"]),
    ],
)
def test_write_operations_broadcast_when_enabled(method_name, args, expected_keys, _reset_broadcast_guard):
    """add, set, and delete should call broadcast_cache_invalidation.apply_async when auto-invalidation is enabled."""
    cache = _make_cache()
    mock_task = mock.MagicMock()
    # add() returns True to indicate key was actually added (new key)
    return_value = True if method_name == 'add' else None
    with (
        mock.patch.object(RedisCache, method_name, return_value=return_value),
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        getattr(cache, method_name)(*args)

    mock_task.apply_async.assert_called_once_with(
        args=[expected_keys],
        kwargs={'origin_node': 'node-a'},
    )


@override_settings(ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
def test_broadcast_skips_self_invalidation(mock_dispatcherd):
    """broadcast_cache_invalidation should skip cache clearing when origin_node matches CLUSTER_HOST_ID."""
    with mock.patch.object(mock_dispatcherd, 'clear_cache') as mock_clear:
        mock_dispatcherd.broadcast_cache_invalidation(['key1'], origin_node='node-a')

    mock_clear.assert_not_called()


@override_settings(ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-b')
def test_broadcast_processes_on_different_node(mock_dispatcherd):
    """broadcast_cache_invalidation should call clear_cache when origin_node differs from CLUSTER_HOST_ID."""
    with mock.patch.object(mock_dispatcherd, 'clear_cache') as mock_clear:
        mock_dispatcherd.broadcast_cache_invalidation(['key1', 'key2'], origin_node='node-a')

    mock_clear.assert_called_once_with(['key1', 'key2'])


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True)
def test_no_broadcast_without_dispatcherd(_reset_broadcast_guard):
    """When dispatcherd is not installed, the cache operation should succeed and log a warning once."""
    import ansible_base.lib.cache.redis_cache as rc

    original = rc._dispatcherd_warning_logged
    rc._dispatcherd_warning_logged = False
    try:
        cache = _make_cache()
        with (
            mock.patch.object(RedisCache, 'set', return_value=None),
            mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', False),
            mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', None),
            mock.patch('ansible_base.lib.cache.redis_cache.logger') as mock_logger,
        ):
            cache.set("key1", "value1")
            cache.set("key2", "value2")

        # Warning should be logged only once, not per-operation
        warning_calls = [call for call in mock_logger.warning.call_args_list if "dispatcherd is not installed" in call[0][0]]
        assert len(warning_calls) == 1
    finally:
        rc._dispatcherd_warning_logged = original


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
def test_reentrancy_guard_prevents_infinite_loop(_reset_broadcast_guard):
    """When _broadcast_guard.active is True, no broadcast should occur (prevents infinite loops)."""
    cache = _make_cache()
    _broadcast_guard.active = True
    mock_task = mock.MagicMock()
    with (
        mock.patch.object(RedisCache, 'delete', return_value=None),
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        cache.delete("key")

    mock_task.apply_async.assert_not_called()


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
def test_broadcast_failure_does_not_break_cache_operation(_reset_broadcast_guard):
    """If apply_async raises, the cache operation itself should still succeed."""
    cache = _make_cache()
    mock_task = mock.MagicMock()
    mock_task.apply_async.side_effect = RuntimeError("pg_notify unavailable")
    with (
        mock.patch.object(RedisCache, 'set', return_value=None) as mock_set,
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        cache.set("key", "value")

    # The underlying set was still called despite broadcast failure
    mock_set.assert_called_once()


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
@pytest.mark.parametrize(
    "method_name, args",
    [
        ("get", ("key",)),
        ("get_many", (["key1", "key2"],)),
        ("has_key", ("key",)),
    ],
)
def test_read_operations_do_not_broadcast(method_name, args, _reset_broadcast_guard):
    """Read-only operations should never trigger broadcast."""
    cache = _make_cache()
    mock_task = mock.MagicMock()
    with (
        mock.patch.object(RedisCache, method_name, return_value=None),
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        getattr(cache, method_name)(*args)

    mock_task.apply_async.assert_not_called()


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
@pytest.mark.parametrize(
    "method_name, args",
    [
        ("touch", ("key",)),
        ("incr", ("key",)),
        ("set_many", ({"key": "value"},)),
        ("delete_many", (["key1", "key2"],)),
        ("clear", ()),
    ],
)
def test_bulk_and_mutate_operations_do_not_broadcast(method_name, args, _reset_broadcast_guard):
    """Bulk writes (set_many, delete_many, clear) and TTL/counter mutations (touch, incr)
    intentionally do not broadcast. See redis_cache.py for rationale."""
    cache = _make_cache()
    mock_task = mock.MagicMock()
    with (
        mock.patch.object(RedisCache, method_name, return_value=None),
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        getattr(cache, method_name)(*args)

    mock_task.apply_async.assert_not_called()


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
def test_add_does_not_broadcast_when_key_exists(_reset_broadcast_guard):
    """add() should NOT broadcast when the key already exists (super().add() returns False)."""
    cache = _make_cache()
    mock_task = mock.MagicMock()
    with (
        mock.patch.object(RedisCache, 'add', return_value=False),
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        result = cache.add("existing-key", "value")

    assert result is False
    mock_task.apply_async.assert_not_called()


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True)
def test_empty_cluster_host_id_warns(_reset_broadcast_guard):
    """When CLUSTER_HOST_ID is not set, a warning should be logged about ineffective self-invalidation guard."""
    import ansible_base.lib.cache.redis_cache as rc

    original = rc._cluster_host_id_warning_logged
    rc._cluster_host_id_warning_logged = False
    try:
        cache = _make_cache()
        mock_task = mock.MagicMock()
        with (
            mock.patch.object(RedisCache, 'set', return_value=None),
            mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
            mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
            mock.patch('ansible_base.lib.cache.redis_cache.logger') as mock_logger,
        ):
            cache.set("key", "value")

        warning_calls = [call for call in mock_logger.warning.call_args_list if "CLUSTER_HOST_ID" in call[0][0]]
        assert len(warning_calls) == 1
    finally:
        rc._cluster_host_id_warning_logged = original


@override_settings(
    DJANGO_REDIS_IGNORE_EXCEPTIONS=True,
    ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True,
    ANSIBLE_BASE_CACHE_BROADCAST_QUEUE='my_custom_queue',
    CLUSTER_HOST_ID='node-a',
)
def test_broadcast_queue_setting(mock_dispatcherd):
    """The broadcast queue name should be read from ANSIBLE_BASE_CACHE_BROADCAST_QUEUE."""
    assert mock_dispatcherd._get_broadcast_queue() == 'my_custom_queue'


def test_broadcast_queue_defaults_to_broadcast(mock_dispatcherd):
    """When ANSIBLE_BASE_CACHE_BROADCAST_QUEUE is not set, the queue should default to 'broadcast'."""
    assert mock_dispatcherd._get_broadcast_queue() == 'broadcast'


@override_settings(DJANGO_REDIS_IGNORE_EXCEPTIONS=True, ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=True, CLUSTER_HOST_ID='node-a')
def test_reentrancy_guard_resets_after_broadcast(_reset_broadcast_guard):
    """The re-entrancy guard should be reset after a broadcast, allowing subsequent operations to broadcast."""
    cache = _make_cache()
    mock_task = mock.MagicMock()
    with (
        mock.patch.object(RedisCache, 'set', return_value=None),
        mock.patch('ansible_base.lib.cache.tasks.HAS_DISPATCHERD', True),
        mock.patch('ansible_base.lib.cache.tasks.broadcast_cache_invalidation', mock_task),
    ):
        cache.set("key1", "value1")
        cache.set("key2", "value2")

    assert mock_task.apply_async.call_count == 2
