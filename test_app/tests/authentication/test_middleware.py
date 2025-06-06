from unittest.mock import patch

from django.conf import settings
from social_core.exceptions import AuthException

from ansible_base.authentication.middleware import (
    AnsibleBaseCsrfViewMiddleware,
    SocialExceptionHandlerMiddleware,
)
from ansible_base.authentication.session import (
    AnsibleBaseCSRFCheck,
    SessionAuthentication,
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


def test_ansible_base_csrf_view_middleware_csrf_trusted_origins_hosts():
    """Test that csrf_trusted_origins_hosts uses get_setting."""
    test_origins = ['https://example.com', 'https://*.test.com']

    with patch('ansible_base.authentication.middleware.get_setting') as mock_get_setting:
        mock_get_setting.return_value = test_origins

        middleware = AnsibleBaseCsrfViewMiddleware(lambda request: None)
        result = middleware.csrf_trusted_origins_hosts

        mock_get_setting.assert_called_once_with('CSRF_TRUSTED_ORIGINS', [])
        # Should strip * from netloc
        assert result == ['example.com', '.test.com']


def test_ansible_base_csrf_view_middleware_allowed_origins_exact():
    """Test that allowed_origins_exact uses get_setting."""
    test_origins = ['https://example.com', 'https://*.test.com']

    with patch('ansible_base.authentication.middleware.get_setting') as mock_get_setting:
        mock_get_setting.return_value = test_origins

        middleware = AnsibleBaseCsrfViewMiddleware(lambda request: None)
        result = middleware.allowed_origins_exact

        mock_get_setting.assert_called_once_with('CSRF_TRUSTED_ORIGINS', [])
        # Should only include origins without *
        assert result == {'https://example.com'}


def test_ansible_base_csrf_view_middleware_allowed_origin_subdomains():
    """Test that allowed_origin_subdomains uses get_setting."""
    test_origins = ['https://*.example.com', 'http://*.test.com']

    with patch('ansible_base.authentication.middleware.get_setting') as mock_get_setting:
        mock_get_setting.return_value = test_origins

        middleware = AnsibleBaseCsrfViewMiddleware(lambda request: None)
        result = middleware.allowed_origin_subdomains

        mock_get_setting.assert_called_once_with('CSRF_TRUSTED_ORIGINS', [])
        # Should group by scheme and strip *
        expected = {'https': ['.example.com'], 'http': ['.test.com']}
        assert dict(result) == expected


def test_ansible_base_csrf_view_middleware_default_value():
    """Test that middleware returns empty/default values when setting is empty."""
    with patch('ansible_base.authentication.middleware.get_setting') as mock_get_setting:
        mock_get_setting.return_value = []

        middleware = AnsibleBaseCsrfViewMiddleware(lambda request: None)

        # Test all three properties
        assert middleware.csrf_trusted_origins_hosts == []
        assert middleware.allowed_origins_exact == set()
        assert dict(middleware.allowed_origin_subdomains) == {}

        # get_setting should be called three times (once for each property)
        assert mock_get_setting.call_count == 3


def test_ansible_base_csrf_check_inherits_from_ansible_base_csrf_view_middleware():
    """Test that AnsibleBaseCSRFCheck inherits from AnsibleBaseCsrfViewMiddleware."""
    csrf_check = AnsibleBaseCSRFCheck(lambda request: None)
    assert isinstance(csrf_check, AnsibleBaseCsrfViewMiddleware)


def test_ansible_base_csrf_check_reject_method():
    """Test that AnsibleBaseCSRFCheck._reject returns the reason."""
    csrf_check = AnsibleBaseCSRFCheck(lambda request: None)
    reason = "Test CSRF failure reason"
    result = csrf_check._reject(None, reason)
    assert result == reason


def test_session_authentication_uses_ansible_base_csrf_check():
    """Test that SessionAuthentication uses AnsibleBaseCSRFCheck for CSRF validation."""
    from unittest.mock import Mock

    # Create a mock request with an authenticated user
    mock_request = Mock()
    mock_request._request = Mock()
    mock_request._request.user = Mock()
    mock_request._request.user.is_active = True

    # Mock the AnsibleBaseCSRFCheck to track its usage
    with patch('ansible_base.authentication.session.AnsibleBaseCSRFCheck') as mock_csrf_check_class:
        mock_csrf_check = Mock()
        mock_csrf_check.process_request.return_value = None
        mock_csrf_check.process_view.return_value = None  # No CSRF error
        mock_csrf_check_class.return_value = mock_csrf_check

        # Create SessionAuthentication instance and call enforce_csrf
        session_auth = SessionAuthentication()
        session_auth.enforce_csrf(mock_request)

        # Verify AnsibleBaseCSRFCheck was instantiated
        mock_csrf_check_class.assert_called_once()

        # Verify process_request and process_view were called
        mock_csrf_check.process_request.assert_called_once_with(mock_request)
        mock_csrf_check.process_view.assert_called_once_with(mock_request, None, (), {})


def test_session_authentication_csrf_failure_raises_permission_denied():
    """Test that SessionAuthentication raises PermissionDenied when CSRF fails."""
    from unittest.mock import Mock

    from rest_framework.exceptions import PermissionDenied

    # Create a mock request with an authenticated user
    mock_request = Mock()
    mock_request._request = Mock()
    mock_request._request.user = Mock()
    mock_request._request.user.is_active = True

    # Mock the AnsibleBaseCSRFCheck to return a CSRF failure reason
    with patch('ansible_base.authentication.session.AnsibleBaseCSRFCheck') as mock_csrf_check_class:
        mock_csrf_check = Mock()
        mock_csrf_check.process_request.return_value = None
        mock_csrf_check.process_view.return_value = "CSRF token missing"  # CSRF error
        mock_csrf_check_class.return_value = mock_csrf_check

        # Create SessionAuthentication instance and call enforce_csrf
        session_auth = SessionAuthentication()

        # Should raise PermissionDenied with the CSRF failure reason
        try:
            session_auth.enforce_csrf(mock_request)
            assert False, "Expected PermissionDenied to be raised"
        except PermissionDenied as e:
            assert "CSRF Failed: CSRF token missing" in str(e)
