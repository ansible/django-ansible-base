from unittest import mock

import pytest
from django.conf import settings
from django.test import override_settings
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.views.ui_auth import generate_ui_auth_data


@pytest.mark.django_db
def test_generate_ui_auth_data_no_authenticators_or_settings():
    response = generate_ui_auth_data()
    assert response == {
        'login_redirect_override': '',
        'passwords': [],
        'ssos': [],
        'show_login_form': False,
        'custom_login_info': '',
        'custom_logo': '',
        'managed_cloud_install': False,
    }


@override_settings(LOGIN_REDIRECT_OVERRIDE='https://example.com')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_login_redirect_url():
    response = generate_ui_auth_data()
    assert response['login_redirect_override'] == settings.LOGIN_REDIRECT_OVERRIDE


@override_settings(LOGIN_REDIRECT_OVERRIDE='/an/absolute/path')
@pytest.mark.django_db
def test_generate_ui_auth_data_valid_login_redirect_path():
    response = generate_ui_auth_data()
    assert response['login_redirect_override'] == settings.LOGIN_REDIRECT_OVERRIDE


@mock.patch("ansible_base.authentication.views.ui_auth.logger")
@override_settings(LOGIN_REDIRECT_OVERRIDE='nonsense')
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_login_redirect_function(logger):
    generate_ui_auth_data()
    logger.error.assert_called_with('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL or absolute path, ignoring')


@mock.patch("ansible_base.authentication.views.ui_auth.logger")
@override_settings(LOGIN_REDIRECT_OVERRIDE='a/relative/path')
@pytest.mark.django_db
def test_generate_ui_auth_invalid_path_login_redirect_function(logger):
    generate_ui_auth_data()
    logger.error.assert_called_with('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL or absolute path, ignoring')


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
    "is_cloud",
    [
        (True),
        (False),
    ],
)
@pytest.mark.django_db
def test_generate_ui_auth_data_managed_cloud(is_cloud):
    with override_settings(ANSIBLE_BASE_MANAGED_CLOUD_INSTALL=is_cloud):
        result = generate_ui_auth_data()
        assert result['managed_cloud_install'] == is_cloud


@pytest.mark.django_db
def test_generate_ui_auth_data_managed_cloud_no_setting():
    result = generate_ui_auth_data()
    assert result['managed_cloud_install'] is False


@pytest.mark.parametrize(
    ('category', 'log_method', 'message'),
    [
        ('api_auth', 'trace', 'Ignoring API auth authenticator test_authenticator because it is not needed for UI support'),
        ('unsupported', 'error', "Don't know how to handle authenticator of type test.unknown"),
    ],
)
@pytest.mark.django_db
@mock.patch("ansible_base.authentication.views.ui_auth.logger")
@mock.patch("ansible_base.authentication.views.ui_auth.Authenticator.objects.filter")
def test_generate_ui_auth_data_handles_non_ui_authenticators(authenticator_filter, logger, category, log_method, message):
    authenticator_filter.return_value = [Authenticator(name='test_authenticator', category=category, type='test.unknown')]

    response = generate_ui_auth_data()

    assert response['passwords'] == []
    assert response['ssos'] == []
    assert response['show_login_form'] is False
    getattr(logger, log_method).assert_called_once_with(message)
    getattr(logger, 'error' if log_method == 'trace' else 'trace').assert_not_called()
