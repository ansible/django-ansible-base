from unittest import mock

import pytest
from django.test import override_settings

from ansible_base.lib.utils.settings import SettingNotSetException, get_setting


@pytest.mark.django_db
def test_unset_setting():
    default_value = 'default_value'
    value = get_setting('UNDEFINED_SETTING', default_value)
    assert value == default_value


@mock.patch("ansible_base.lib.utils.settings.logger")
@override_settings(ANSIBLE_BASE_SETTINGS_FUNCTION='junk')
def test_invalid_settings_function(logger):
    default_value = 'default_value'
    value = get_setting('UNDEFINED_SETTING', default_value)
    assert value == default_value
    logger.exception.assert_called_once_with(
        "ANSIBLE_BASE_SETTINGS_FUNCTION was set but calling it as a function failed (see exception), ignoring error and attempting to load from settings"
    )


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
