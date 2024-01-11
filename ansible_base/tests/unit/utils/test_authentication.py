from unittest import mock

import pytest
from django.conf import settings
from django.test import override_settings

from ansible_base.utils.authentication import generate_ui_auth_data


@pytest.mark.django_db
def test_generate_ui_auth_data_no_authenticators_or_settings():
    response = generate_ui_auth_data()
    assert response == {
        'login_redirect_override': '',
        'passwords': [],
        'show_login_form': False,
        'ssos': [],
        'custom_login_info': '',
        'custom_logo': '',
    }


@override_settings(LOGIN_REDIRECT_OVERRIDE='https://example.com')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_login_redirect():
    response = generate_ui_auth_data()
    assert response == {
        'login_redirect_override': settings.LOGIN_REDIRECT_OVERRIDE,
        'passwords': [],
        'show_login_form': False,
        'ssos': [],
        'custom_login_info': '',
        'custom_logo': '',
    }


@mock.patch("ansible_base.utils.authentication.logger")
@override_settings(LOGIN_REDIRECT_OVERRIDE='nonsense')
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_login_redirect_function(logger):
    generate_ui_auth_data()
    logger.exception.assert_called_with('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL, ignoring')


@override_settings(custom_login_info='Login with your username and password')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_login_info():
    response = generate_ui_auth_data()
    assert response == {
        'login_redirect_override': '',
        'passwords': [],
        'show_login_form': False,
        'ssos': [],
        'custom_login_info': 'Login with your username and password',
        'custom_logo': '',
    }


@mock.patch("ansible_base.utils.authentication.logger")
@override_settings(custom_login_info=12343)
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_login_info(logger):
    generate_ui_auth_data()
    logger.exception.assert_called_with('custom_login_info was set but was not a valid string, ignoring')


@override_settings(custom_logo='data:image/gif;base64,R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs=')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_logo_image():
    response = generate_ui_auth_data()
    assert response == {
        'login_redirect_override': '',
        'passwords': [],
        'show_login_form': False,
        'ssos': [],
        'custom_login_info': '',
        'custom_logo': 'data:image/gif;base64,R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs=',
    }


@mock.patch("ansible_base.utils.authentication.logger")
@override_settings(custom_logo='wrong formatted image data')
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_logo_image_format(logger):
    generate_ui_auth_data()
    logger.exception.assert_called_with('Invalid format for custom logo. Must be a data URL with a base64-encoded GIF, PNG or JPEG image.')


@mock.patch("ansible_base.utils.authentication.logger")
@override_settings(custom_logo='data:image/gif;base64,badimagedata')
@pytest.mark.django_db
def test_generate_ui_auth_data_bad_logo_image_data(logger):
    generate_ui_auth_data()
    logger.exception.assert_called_with('Invalid base64-encoded data in data URL.')
