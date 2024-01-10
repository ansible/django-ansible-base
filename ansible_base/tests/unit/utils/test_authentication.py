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
    }


@mock.patch("ansible_base.utils.authentication.logger")
@override_settings(LOGIN_REDIRECT_OVERRIDE='nonsense')
@pytest.mark.django_db
def test_generate_ui_auth_data_invalid_login_redirect_function(logger):
    generate_ui_auth_data()
    logger.exception.assert_called_with('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL, ignoring')
