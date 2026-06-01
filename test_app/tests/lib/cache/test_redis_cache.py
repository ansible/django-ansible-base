from unittest import mock

import pytest
from django.core.cache.backends.redis import RedisCache
from django.test import override_settings
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from ansible_base.lib.cache.redis_cache import CONNECTION_INTERRUPTED_SENTINEL, DABRedisCache, optionally_ignore_exceptions


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
