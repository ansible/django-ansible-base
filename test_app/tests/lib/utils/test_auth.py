import pytest
from unittest.mock import patch
from ansible_base.lib.utils.auth import get_model_from_settings
from django.core.exceptions import ImproperlyConfigured


def test_get_model_from_settings_invalid_setting_name():
    with pytest.raises(AttributeError):
        get_model_from_settings('jimbob')


@patch('ansible_base.lib.utils.auth.settings')
def test_get_model_from_settings_lookup_error(mock_settings):
    mock_settings.FOOBAR = 'no_such_model'
    with pytest.raises(ImproperlyConfigured):
        get_model_from_settings('FOOBAR')


@patch('ansible_base.lib.utils.auth.settings')
def test_get_model_from_settings_value_error(mock_settings):
    mock_settings.FOOBAR = 'User'
    with pytest.raises(ImproperlyConfigured):
        get_model_from_settings('FOOBAR')
