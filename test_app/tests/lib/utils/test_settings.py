from unittest import mock

import pytest
from django.test import override_settings

from ansible_base.lib.dynamic_config.settings_logic import get_dab_settings
from ansible_base.lib.utils.settings import SettingNotSetException, get_setting, is_aoc_instance


@pytest.mark.django_db
def test_unset_setting():
    default_value = 'default_value'
    value = get_setting('UNDEFINED_SETTING', default_value)
    assert value == default_value


@mock.patch("ansible_base.lib.utils.settings.logger")
@override_settings(ANSIBLE_BASE_SETTINGS_FUNCTION='test_app.tests.lib.utils.test_views.version_function_issue')
@pytest.mark.parametrize('log_exception_flag', [False, True])
def test_invalid_settings_function(logger, log_exception_flag):
    default_value = 'default_value'
    value = get_setting('UNDEFINED_SETTING', default_value, log_exception_flag)
    assert value == default_value

    if log_exception_flag:
        logger.exception.assert_called_once_with(
            "ANSIBLE_BASE_SETTINGS_FUNCTION was set but calling it as a function failed (see exception), ignoring error and attempting to load from settings"
        )
    else:
        logger.exception.assert_not_called()


def setting_getter_function(setting_name):
    if setting_name == 'exists':
        return 'hi'
    else:
        raise SettingNotSetException


@pytest.mark.parametrize(
    "setting_name,default,expected_value",
    [
        ('exists', 4, 'hi'),
        ('does_not_exists', 4, 4),
    ],
)
@override_settings(ANSIBLE_BASE_SETTINGS_FUNCTION='test_app.tests.lib.utils.test_settings.setting_getter_function')
def test_settings_from_function(setting_name, default, expected_value):
    value = get_setting(setting_name, default)
    assert value == expected_value


@pytest.mark.parametrize(
    "setting_value,expected_value,expected_log_output",
    [
        (None, False, True),
        (True, True, False),
        (False, False, False),
        (1, True, False),
        ('a', False, True),
    ],
)
def test_is_aoc_instance(setting_value, expected_value, expected_log_output, expected_log):
    with override_settings(ANSIBLE_BASE_MANAGED_CLOUD_INSTALL=setting_value):
        with expected_log(
            'ansible_base.lib.utils.settings.logger',
            'error',
            'was set but could not be converted to a boolean, assuming false',
            assert_not_called=(not expected_log_output),
        ):
            assert expected_value == is_aoc_instance()


def test_fallback_cache():
    redis_cache = {'default': {'BACKEND': 'django_redis.cache.RedisCache'}}

    assert get_dab_settings([], caches=redis_cache)['CACHES'] == redis_cache

    fallback_cache = {
        'default': {'BACKEND': 'ansible_base.lib.cache.fallback_cache.DABCacheWithFallback'},
        'primary': {'BACKEND': 'django_redis.cache.RedisCache'},
    }

    with pytest.raises(RuntimeError):
        get_dab_settings([], caches=fallback_cache)

    assert 'CACHES' not in get_dab_settings([], caches=None)
