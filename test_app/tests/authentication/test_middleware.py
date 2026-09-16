from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from django.conf import settings
from social_core.exceptions import AuthCanceled, AuthException, AuthForbidden

from ansible_base.authentication.middleware import SocialExceptionHandlerMiddleware
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.authentication.utils.oauth_http import (
    OAUTH_HTTP_ERROR_BODY_LIMIT,
    format_oauth_http_error,
    oauth_http_error_body,
)


def test_social_exception_handler_mw():
    class Strategy:
        def setting(self, name):
            return settings.LOGIN_ERROR_URL

    class Backend:
        def __init__(self):
            self.name = "test"

    class Request:
        def __init__(self):
            self.social_strategy = Strategy()
            self.backend = Backend()

    mw = SocialExceptionHandlerMiddleware(None)
    url = mw.get_redirect_uri(Request(), AuthException("test"))
    assert url == "/?auth_failed"


@mock.patch("ansible_base.authentication.middleware.log_auth_error")
def test_social_exception_handler_mw_logs_provider_response(mock_log):
    class Strategy:
        def setting(self, name):
            return settings.LOGIN_ERROR_URL

    class Request:
        social_strategy = Strategy()
        backend = SimpleNamespace(name="azuread-slug")

    response = mock.Mock()
    response.text = '{"error":"invalid_client","error_codes":[7000215]}'
    exception = AuthCanceled("backend", response=response)

    mw = SocialExceptionHandlerMiddleware(None)
    assert mw.get_redirect_uri(Request(), exception) == "/?auth_failed"
    message = mock_log.call_args[0][0]
    assert "provider response=" in message
    assert "7000215" in message


def test_oauth_http_error_body_truncates_and_handles_missing():
    assert oauth_http_error_body(None) == ""
    response = mock.Mock()
    response.text = "x" * (OAUTH_HTTP_ERROR_BODY_LIMIT + 50)
    assert len(oauth_http_error_body(response)) == OAUTH_HTTP_ERROR_BODY_LIMIT

    class Broken:
        @property
        def text(self):
            raise RuntimeError("boom")

    assert oauth_http_error_body(Broken()) == ""


def test_format_oauth_http_error_includes_status_and_body():
    err = requests.HTTPError("401")
    err.response = mock.Mock(status_code=401, text='{"error":"invalid_client"}')
    line = format_oauth_http_error("Test Azure AD", err)
    assert "Test Azure AD" in line
    assert "status=401" in line
    assert "invalid_client" in line


@mock.patch("ansible_base.authentication.social_auth.log_auth_error")
def test_social_auth_mixin_request_logs_http_error(mock_log):
    http_err = requests.HTTPError("401")
    http_err.response = mock.Mock(
        status_code=401,
        text='{"error":"invalid_client","error_description":"AADSTS7000215"}',
    )

    class RaisingParent:
        def request(self, *args, **kwargs):
            raise http_err

    class Plugin(SocialAuthMixin, RaisingParent):
        def __init__(self):
            self.database_instance = SimpleNamespace(name="Test Azure AD")

    plugin = object.__new__(Plugin)
    plugin.database_instance = SimpleNamespace(name="Test Azure AD")

    with pytest.raises(requests.HTTPError):
        plugin.request("https://example.invalid/oauth2/token")

    mock_log.assert_called_once()
    message = mock_log.call_args[0][0]
    assert "OAuth HTTP error for authenticator 'Test Azure AD'" in message
    assert "status=401" in message
    assert "AADSTS7000215" in message


def test_auth_forbidden_has_no_response_for_middleware():
    """401 mapping in social-core 4.5.4 does not attach response; mixin log is required."""
    exception = AuthForbidden("backend")
    assert getattr(exception, "response", None) in (None, "")
