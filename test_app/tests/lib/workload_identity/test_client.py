"""Tests for Workload Identity Client."""

import time
from unittest import mock

import jwt as pyjwt
import pytest
import requests

from ansible_base.lib.workload_identity import (
    InvalidTokenError,
    ServiceAuthenticationError,
    TokenRequestError,
    WorkloadIdentityClient,
    WorkloadIdentityTokenRequest,
    WorkloadIdentityTokenResponse,
)


class TestWorkloadIdentityTokenTypes:
    """Test the NamedTuple types."""

    def test_request_type_creation(self):
        """Test that WorkloadIdentityTokenRequest can be created with correct fields."""
        request = WorkloadIdentityTokenRequest(
            claims={"sub": "user123", "aud": "my-service"},
            scope="read write",
        )

        assert request.claims == {"sub": "user123", "aud": "my-service"}
        assert request.scope == "read write"

    def test_request_type_as_dict(self):
        """Test that WorkloadIdentityTokenRequest can be converted to dict."""
        request = WorkloadIdentityTokenRequest(
            claims={"sub": "user123"},
            scope="read",
        )

        request_dict = request._asdict()
        assert request_dict == {
            "claims": {"sub": "user123"},
            "scope": "read",
        }

    def test_response_type_creation(self):
        """Test that WorkloadIdentityTokenResponse can be created with correct fields."""
        response = WorkloadIdentityTokenResponse(
            access_token="eyJhbGci...",
            token_type="Bearer",
            expires_in=3600,
            scope="read write",
        )

        assert response.access_token == "eyJhbGci..."
        assert response.token_type == "Bearer"
        assert response.expires_in == 3600
        assert response.scope == "read write"

    def test_response_type_defaults(self):
        """Test that WorkloadIdentityTokenResponse has correct defaults."""
        response = WorkloadIdentityTokenResponse(access_token="token123")

        assert response.access_token == "token123"
        assert response.token_type == "Bearer"
        assert response.expires_in is None
        assert response.scope is None


class TestWorkloadIdentityClient:
    """Test the WorkloadIdentityClient class."""

    def test_client_initialization(self):
        """Test that client can be initialized with correct parameters."""
        client = WorkloadIdentityClient(
            base_url="https://gateway.example.com",
            jwt_user_id=1,
            jwt_expiration=60,
            verify_https=True,
            raise_if_bad_request=True,
        )

        assert client.base_url == "https://gateway.example.com"
        assert client.jwt_user_id == 1
        assert client.jwt_expiration == 60
        assert client.verify_https is True
        assert client.raise_if_bad_request is True

    def test_client_base_url_strips_trailing_slash(self):
        """Test that trailing slash is removed from base_url."""
        client = WorkloadIdentityClient(base_url="https://gateway.example.com/")

        assert client.base_url == "https://gateway.example.com"

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    def test_service_token_refresh(self, mock_get_service_token):
        """Test that service token is refreshed correctly."""
        mock_get_service_token.return_value = "test-service-token"

        client = WorkloadIdentityClient(
            base_url="https://gateway.example.com",
            jwt_user_id=1,
            jwt_expiration=60,
        )

        # Initial state - no token
        assert client._jwt is None
        assert client._jwt_timeout is None

        # Refresh token
        client.refresh_jwt()

        # Check token was generated
        assert client._jwt == "test-service-token"
        assert client._jwt_timeout is not None
        assert client._jwt_timeout > time.time()

        # Verify get_service_token was called correctly
        mock_get_service_token.assert_called_once_with(1, expiration=60)

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    def test_service_token_property_auto_refresh(self, mock_get_service_token):
        """Test that jwt property automatically refreshes expired tokens."""
        mock_get_service_token.return_value = "new-token"

        client = WorkloadIdentityClient(
            base_url="https://gateway.example.com",
            jwt_expiration=60,
        )

        # First access - should refresh
        token1 = client.jwt
        assert token1 == "new-token"
        assert mock_get_service_token.call_count == 1

        # Second access immediately - should NOT refresh (token still valid)
        token2 = client.jwt
        assert token2 == "new-token"
        assert mock_get_service_token.call_count == 1

        # Simulate token expiration
        client._jwt_timeout = time.time() - 1

        # Third access - should refresh (token expired)
        mock_get_service_token.return_value = "refreshed-token"
        token3 = client.jwt
        assert token3 == "refreshed-token"
        assert mock_get_service_token.call_count == 2

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    def test_service_token_refresh_error(self, mock_get_service_token):
        """Test that service token refresh raises ServiceAuthenticationError on failure."""
        mock_get_service_token.side_effect = Exception("Token generation failed")

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(ServiceAuthenticationError) as exc_info:
            client.refresh_jwt()

        assert "Failed to refresh service token" in str(exc_info.value)

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    def test_service_auth_header(self, mock_get_service_token):
        """Test that service_auth_header returns correct header."""
        mock_get_service_token.return_value = "test-service-token"

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        header = client.service_auth_header

        assert header == {"X-ANSIBLE-SERVICE-AUTH": "test-service-token"}

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_success(self, mock_request, mock_get_service_token):
        """Test successful token request."""
        # Setup mocks
        mock_get_service_token.return_value = "service-token"

        # Create a valid JWT token for the response
        test_jwt = pyjwt.encode(
            {"sub": "user123", "aud": "my-service", "scope": "read write"},
            "secret",
            algorithm="HS256",
        )

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": test_jwt,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read write",
        }
        mock_request.return_value = mock_response

        # Make request
        client = WorkloadIdentityClient(base_url="https://gateway.example.com")
        response = client.request_token(
            claims={"sub": "user123", "aud": "my-service"},
            scope="read write",
        )

        # Verify response
        assert isinstance(response, WorkloadIdentityTokenResponse)
        assert response.access_token == test_jwt
        assert response.token_type == "Bearer"
        assert response.expires_in == 3600
        assert response.scope == "read write"

        # Verify request was made correctly
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["url"] == "https://gateway.example.com/api/gateway/v1/workload_identity_tokens"
        assert call_kwargs["json"] == {
            "claims": {"sub": "user123", "aud": "my-service"},
            "scope": "read write",
        }
        assert call_kwargs["headers"]["X-ANSIBLE-SERVICE-AUTH"] == "service-token"
        assert call_kwargs["verify"] is True

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_http_error(self, mock_request, mock_get_service_token):
        """Test that HTTP errors raise TokenRequestError."""
        mock_get_service_token.return_value = "service-token"

        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_token(claims={"sub": "user123"}, scope="read")

        assert "401 Unauthorized" in str(exc_info.value)

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_missing_access_token(self, mock_request, mock_get_service_token):
        """Test that missing access_token in response raises TokenRequestError."""
        mock_get_service_token.return_value = "service-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "token_type": "Bearer",
            # Missing access_token field
        }
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_token(claims={"sub": "user123"}, scope="read")

        assert "missing 'access_token' field" in str(exc_info.value)

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_invalid_jwt(self, mock_request, mock_get_service_token):
        """Test that invalid JWT in response raises InvalidTokenError."""
        mock_get_service_token.return_value = "service-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "not-a-valid-jwt-token",
            "token_type": "Bearer",
        }
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(InvalidTokenError) as exc_info:
            client.request_token(claims={"sub": "user123"}, scope="read")

        assert "Invalid JWT token" in str(exc_info.value)

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_json_parse_error(self, mock_request, mock_get_service_token):
        """Test that JSON parse errors raise TokenRequestError."""
        mock_get_service_token.return_value = "service-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_token(claims={"sub": "user123"}, scope="read")

        assert "Failed to parse response" in str(exc_info.value)

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_network_error(self, mock_request, mock_get_service_token):
        """Test that network errors raise TokenRequestError."""
        mock_get_service_token.return_value = "service-token"
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection failed")

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_token(claims={"sub": "user123"}, scope="read")

        assert "Request failed" in str(exc_info.value)

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_with_various_scopes(self, mock_request, mock_get_service_token):
        """Test that different scope strings are handled correctly."""
        mock_get_service_token.return_value = "service-token"

        test_jwt = pyjwt.encode({"sub": "test"}, "secret", algorithm="HS256")

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": test_jwt,
            "token_type": "Bearer",
        }
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        # Test different scope values
        for scope in ["read", "write", "read write", "read write admin"]:
            response = client.request_token(claims={"sub": "test"}, scope=scope)
            assert response.access_token == test_jwt

            # Verify scope was sent in request
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["json"]["scope"] == scope

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_request_token_with_various_claims(self, mock_request, mock_get_service_token):
        """Test that different claims dictionaries are handled correctly."""
        mock_get_service_token.return_value = "service-token"

        test_jwt = pyjwt.encode({"sub": "test"}, "secret", algorithm="HS256")

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": test_jwt,
            "token_type": "Bearer",
        }
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        # Test different claims
        test_claims = [
            {"sub": "user123"},
            {"sub": "user123", "aud": "my-service"},
            {"sub": "user123", "aud": "my-service", "iss": "gateway"},
            {"sub": "user123", "roles": ["admin", "user"], "permissions": ["read", "write"]},
        ]

        for claims in test_claims:
            response = client.request_token(claims=claims, scope="read")
            assert response.access_token == test_jwt

            # Verify claims were sent in request
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["json"]["claims"] == claims

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    def test_client_with_no_https_verification(self, mock_get_service_token):
        """Test that HTTPS verification can be disabled."""
        mock_get_service_token.return_value = "service-token"

        client = WorkloadIdentityClient(
            base_url="https://gateway.example.com",
            verify_https=False,
        )

        assert client.verify_https is False

    @mock.patch("ansible_base.lib.workload_identity.client.get_service_token")
    @mock.patch("ansible_base.lib.workload_identity.client.requests.request")
    def test_client_without_raise_on_error(self, mock_request, mock_get_service_token):
        """Test that raise_if_bad_request=False doesn't raise on HTTP errors."""
        mock_get_service_token.return_value = "service-token"

        mock_response = mock.Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.side_effect = ValueError("No JSON in error response")
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(
            base_url="https://gateway.example.com",
            raise_if_bad_request=False,
        )

        # Should not raise, but response parsing will fail
        with pytest.raises(TokenRequestError):
            # Will fail on JSON parse or missing access_token
            client.request_token(claims={"sub": "test"}, scope="read")


class TestGetWorkloadIdentityClient:
    """Test the get_workload_identity_client factory function."""

    @mock.patch("ansible_base.lib.workload_identity.client.get_resource_server_config")
    def test_factory_creates_client_from_config(self, mock_get_config):
        """Test that factory function creates client with config values."""
        from ansible_base.lib.workload_identity import get_workload_identity_client

        mock_get_config.return_value = {
            "URL": "https://gateway.example.com",
            "VALIDATE_HTTPS": True,
        }

        client = get_workload_identity_client()

        assert client.base_url == "https://gateway.example.com"
        assert client.verify_https is True
        mock_get_config.assert_called_once()

    @mock.patch("ansible_base.lib.workload_identity.client.get_resource_server_config")
    def test_factory_passes_kwargs_to_client(self, mock_get_config):
        """Test that factory function passes additional kwargs to client."""
        from ansible_base.lib.workload_identity import get_workload_identity_client

        mock_get_config.return_value = {
            "URL": "https://gateway.example.com",
            "VALIDATE_HTTPS": True,
        }

        client = get_workload_identity_client(
            jwt_user_id=123,
            jwt_expiration=120,
            raise_if_bad_request=False,
        )

        assert client.jwt_user_id == 123
        assert client.jwt_expiration == 120
        assert client.raise_if_bad_request is False

    @mock.patch("ansible_base.lib.workload_identity.client.get_resource_server_config")
    def test_factory_with_https_disabled(self, mock_get_config):
        """Test that factory respects VALIDATE_HTTPS=False from config."""
        from ansible_base.lib.workload_identity import get_workload_identity_client

        mock_get_config.return_value = {
            "URL": "http://localhost:8000",
            "VALIDATE_HTTPS": False,
        }

        client = get_workload_identity_client()

        assert client.base_url == "http://localhost:8000"
        assert client.verify_https is False
