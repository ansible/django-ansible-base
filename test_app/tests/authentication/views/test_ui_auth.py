from unittest import mock

import pytest
from django.conf import settings
from django.test import override_settings
from rest_framework.serializers import ValidationError

from ansible_base.authentication.views.ui_auth import generate_ui_auth_data


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
        'managed_cloud_install': False,
    }


@override_settings(LOGIN_REDIRECT_OVERRIDE='https://example.com')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_login_redirect():
    response = generate_ui_auth_data()
    assert response['login_redirect_override'] == settings.LOGIN_REDIRECT_OVERRIDE


@mock.patch("ansible_base.authentication.views.ui_auth.logger")
@override_settings(LOGIN_REDIRECT_OVERRIDE='nonsense')
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_login_redirect_function(logger):
    generate_ui_auth_data()
    logger.error.assert_called_with('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL, ignoring')


@override_settings(custom_login_info='Login with your username and password')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_login_info():
    response = generate_ui_auth_data()
    assert response['custom_login_info'] == 'Login with your username and password'


@override_settings(custom_login_info=12343)
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_login_info():
    with pytest.raises(ValidationError) as e:
        generate_ui_auth_data()
    assert "custom_login_info was set but was not a valid string, ignoring" in str(e.value)


@override_settings(custom_logo='data:image/gif;base64,R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs=')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_logo_image():
    response = generate_ui_auth_data()
    assert response['custom_logo'] == 'data:image/gif;base64,R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs='


@mock.patch("ansible_base.authentication.views.ui_auth.logger")
@override_settings(custom_logo='wrong formatted image data')
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_logo_image_format(logger):
    generate_ui_auth_data()
    logger.error.assert_called_with('custom_logo was set but was not a valid image data, ignoring')


@mock.patch("ansible_base.authentication.views.ui_auth.logger")
@override_settings(custom_logo='data:image/gif;base64,baddata')
@pytest.mark.django_db
def test_generate_ui_auth_data_bad_logo_image_data(logger):
    generate_ui_auth_data()
    logger.error.assert_called_with('custom_logo was set but was not a valid image data, ignoring')


@pytest.mark.parametrize(
    "setting,expected_result",
    [
        (None, None),
        (True, True),
        (False, False),
        ('a', None),
    ],
)
@pytest.mark.django_db
def test_generate_ui_auth_data_managed_cloud(expected_log, setting, expected_result):
    with override_settings(ANSIBLE_BASE_MANAGED_CLOUD_INSTALL=setting):
        expect_log_called = False
        if expected_result is None:
            expect_log_called = True
            expected_result = False
        with expected_log(
            'ansible_base.authentication.views.ui_auth.logger',
            'error',
            'was set but could not be converted to a boolean, assuming false',
            assert_not_called=(not expect_log_called),
        ):
            result = generate_ui_auth_data()
            assert result['managed_cloud_install'] == expected_result


@pytest.mark.django_db
def test_generate_ui_auth_data_managed_cloud_no_setting(expected_log):
    with expected_log(
        'ansible_base.authentication.views.ui_auth.logger', 'error', 'was set but could not be converted to a boolean, assuming false', assert_not_called=True
    ):
        result = generate_ui_auth_data()
        assert result['managed_cloud_install'] is False
