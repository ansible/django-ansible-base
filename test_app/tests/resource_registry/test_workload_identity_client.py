"""Tests for Workload Identity Client."""

import time
from unittest import mock

import jwt as pyjwt
import pytest
import requests

from ansible_base.resource_registry.workload_identity_client import (
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
            claims={"id": 2, "name": "my-example-job"},
            scope="aap_controller_automation_job",
            audience="https://vault.example.com",
        )

        assert request.claims == {"id": 2, "name": "my-example-job"}
        assert request.scope == "aap_controller_automation_job"
        assert request.audience == "https://vault.example.com"
        assert request.workload_ttl_seconds is None

    def test_request_type_with_custom_ttl(self):
        """Test that workload_ttl_seconds can be set on the request type."""
        request = WorkloadIdentityTokenRequest(
            claims={"id": 2, "name": "my-example-job"},
            scope="aap_controller_automation_job",
            audience="https://vault.example.com",
            workload_ttl_seconds=3600,
        )

        assert request.workload_ttl_seconds == 3600

    def test_request_type_as_dict(self):
        """Test that WorkloadIdentityTokenRequest can be converted to dict."""
        request = WorkloadIdentityTokenRequest(
            claims={"id": 1, "name": "test-job"},
            scope="aap_controller_automation_job",
            audience="https://vault.example.com",
        )

        request_dict = request._asdict()
        assert request_dict == {
            "claims": {"id": 1, "name": "test-job"},
            "scope": "aap_controller_automation_job",
            "audience": "https://vault.example.com",
            "workload_ttl_seconds": None,
        }

    def test_response_type_creation(self):
        """Test that WorkloadIdentityTokenResponse can be created with correct fields."""
        response = WorkloadIdentityTokenResponse(jwt="eyJhbGci...")

        assert response.jwt == "eyJhbGci..."


class TestWorkloadIdentityClient:
    """Test the WorkloadIdentityClient class."""

    def _setup_mock_response(self, mock_request, mock_get_service_token, jwt_payload=None):
        """Configure mocks for a successful HTTP request returning a JWT."""
        mock_get_service_token.return_value = "service-token"
        payload = jwt_payload or {"sub": "job_1"}
        test_jwt = pyjwt.encode(payload, "test-secret-key-for-workload-identity", algorithm="HS256")
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jwt": test_jwt}
        mock_request.return_value = mock_response
        return test_jwt

    def test_client_initialization(self):
        """Test that client can be initialized with correct parameters."""
        client = WorkloadIdentityClient(
            base_url="https://gateway.example.com",
            jwt_user_id=1,
            jwt_expiration=60,
            verify_https=True,
            raise_if_bad_request=True,
        )

        assert client.base_url == "https://gateway.example.com/"
        assert client.jwt_user_id == "1"  # Converted to string
        assert client.jwt_expiration == 60
        assert client.verify_https is True
        assert client.raise_if_bad_request is True

    def test_client_base_url_has_trailing_slash(self):
        """Test that base_url always ends with trailing slash."""
        client = WorkloadIdentityClient(base_url="https://gateway.example.com/")
        assert client.base_url == "https://gateway.example.com/"

        # Also test without trailing slash - should be added
        client2 = WorkloadIdentityClient(base_url="https://gateway.example.com")
        assert client2.base_url == "https://gateway.example.com/"

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
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
        mock_get_service_token.assert_called_once_with("1", expiration=60)  # jwt_user_id converted to string

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
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

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_success(self, mock_request, mock_get_service_token):
        """Test successful token request includes all expected fields in the request body."""
        test_jwt = self._setup_mock_response(
            mock_request,
            mock_get_service_token,
            jwt_payload={"sub": "job_2", "aud": "https://vault.example.com", "scope": "aap_controller_automation_job"},
        )

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")
        response = client.request_workload_jwt(
            claims={"id": 2, "name": "my-example-job"},
            scope="aap_controller_automation_job",
            audience="https://vault.example.com",
        )

        assert isinstance(response, WorkloadIdentityTokenResponse)
        assert response.jwt == test_jwt

        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["url"] == "https://gateway.example.com/api/gateway/v1/workload_identity_tokens/"
        expected_json = {
            "claims": {"id": 2, "name": "my-example-job"},
            "scope": "aap_controller_automation_job",
            "audience": "https://vault.example.com",
        }
        assert call_kwargs["json"] == expected_json
        assert "workload_ttl_seconds" not in call_kwargs["json"]  # None = omitted (platform fallback)
        assert call_kwargs["headers"]["X-ANSIBLE-SERVICE-AUTH"] == "service-token"
        assert call_kwargs["verify"] is True

    @pytest.mark.parametrize(
        "workload_ttl_seconds,expected_in_json",
        [
            (3600, 3600),
            (None, None),  # omitted = platform fallback
        ],
        ids=["custom-ttl-sent-to-gateway", "none-omitted-platform-fallback"],
    )
    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_workload_ttl_seconds(self, mock_request, mock_get_service_token, workload_ttl_seconds, expected_in_json):
        """Test that workload_ttl_seconds is included when set, omitted when None.

        None (or omit) signals the Gateway to use its platform fallback (jwt_default_ttl_seconds).
        """
        self._setup_mock_response(mock_request, mock_get_service_token)

        kwargs = {
            "claims": {"id": 1, "name": "test-job"},
            "scope": "aap_controller_automation_job",
            "audience": "https://vault.example.com",
        }
        if workload_ttl_seconds:
            kwargs["workload_ttl_seconds"] = workload_ttl_seconds

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")
        client.request_workload_jwt(**kwargs)

        json_body = mock_request.call_args[1]["json"]
        if expected_in_json is None:
            assert "workload_ttl_seconds" not in json_body
        else:
            assert json_body["workload_ttl_seconds"] == expected_in_json

    @pytest.mark.parametrize("invalid_ttl", [0, -1, -3600])
    def test_request_workload_jwt_rejects_invalid_ttl(self, invalid_ttl):
        """Test that workload_ttl_seconds=0 or negative raises ValueError (Gateway rejects 0)."""
        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(ValueError, match=r"must be None.*or >= 1"):
            client.request_workload_jwt(
                claims={"id": 1, "name": "test-job"},
                scope="aap_controller_automation_job",
                audience="https://vault.example.com",
                workload_ttl_seconds=invalid_ttl,
            )

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_http_error(self, mock_request, mock_get_service_token):
        """Test that HTTP errors raise TokenRequestError."""
        mock_get_service_token.return_value = "service-token"
        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_workload_jwt(
                claims={"id": 1, "name": "test"},
                scope="aap_controller_automation_job",
                audience="https://vault.example.com",
            )

        assert "401 Unauthorized" in str(exc_info.value)

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_missing_jwt_field(self, mock_request, mock_get_service_token):
        """Test that missing jwt field in response raises TokenRequestError."""
        mock_get_service_token.return_value = "service-token"
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_workload_jwt(
                claims={"id": 1, "name": "test"},
                scope="aap_controller_automation_job",
                audience="https://vault.example.com",
            )

        assert "missing 'jwt' field" in str(exc_info.value)

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_json_parse_error(self, mock_request, mock_get_service_token):
        """Test that JSON parse errors raise TokenRequestError."""
        mock_get_service_token.return_value = "service-token"
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_request.return_value = mock_response

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_workload_jwt(
                claims={"id": 1, "name": "test"},
                scope="aap_controller_automation_job",
                audience="https://vault.example.com",
            )

        assert "Failed to parse response" in str(exc_info.value)

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_network_error(self, mock_request, mock_get_service_token):
        """Test that network errors raise TokenRequestError."""
        mock_get_service_token.return_value = "service-token"
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection failed")

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        with pytest.raises(TokenRequestError) as exc_info:
            client.request_workload_jwt(
                claims={"id": 1, "name": "test"},
                scope="aap_controller_automation_job",
                audience="https://vault.example.com",
            )

        assert "Request failed" in str(exc_info.value)

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_with_various_scopes(self, mock_request, mock_get_service_token):
        """Test that different scope strings are handled correctly."""
        test_jwt = self._setup_mock_response(mock_request, mock_get_service_token)

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        for scope in ["aap_controller_automation_job", "aap_eda_automation_job", "custom_scope"]:
            response = client.request_workload_jwt(
                claims={"id": 1, "name": "test"},
                scope=scope,
                audience="https://vault.example.com",
            )
            assert response.jwt == test_jwt
            assert mock_request.call_args[1]["json"]["scope"] == scope

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
    def test_request_workload_jwt_with_various_claims(self, mock_request, mock_get_service_token):
        """Test that different claims dictionaries are handled correctly."""
        test_jwt = self._setup_mock_response(mock_request, mock_get_service_token)

        client = WorkloadIdentityClient(base_url="https://gateway.example.com")

        test_claims = [
            {"id": 1, "name": "job1"},
            {"id": 2, "name": "job2", "project": "test-project"},
            {"id": 3, "name": "job3", "metadata": {"tags": ["prod", "critical"]}},
            {"id": 4, "name": "job4", "organization": "my-org", "team": "devops"},
        ]

        for claims in test_claims:
            response = client.request_workload_jwt(
                claims=claims,
                scope="aap_controller_automation_job",
                audience="https://vault.example.com",
            )
            assert response.jwt == test_jwt
            assert mock_request.call_args[1]["json"]["claims"] == claims

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    def test_client_with_no_https_verification(self, mock_get_service_token):
        """Test that HTTPS verification can be disabled."""
        mock_get_service_token.return_value = "service-token"

        client = WorkloadIdentityClient(
            base_url="https://gateway.example.com",
            verify_https=False,
        )

        assert client.verify_https is False

    @mock.patch("ansible_base.resource_registry.service_client.get_service_token")
    @mock.patch("ansible_base.resource_registry.service_client.requests.request")
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
            # Will fail on JSON parse or missing jwt field
            client.request_workload_jwt(
                claims={"id": 1, "name": "test"},
                scope="aap_controller_automation_job",
                audience="https://vault.example.com",
            )


class TestGetWorkloadIdentityClient:
    """Test the get_workload_identity_client factory function."""

    @mock.patch("ansible_base.resource_registry.workload_identity_client.get_resource_server_config")
    def test_factory_creates_client_from_config(self, mock_get_config):
        """Test that factory function creates client with config values."""
        from ansible_base.resource_registry.workload_identity_client import get_workload_identity_client

        mock_get_config.return_value = {
            "URL": "https://gateway.example.com",
            "VALIDATE_HTTPS": True,
        }

        client = get_workload_identity_client()

        assert client.base_url == "https://gateway.example.com/"
        assert client.verify_https is True
        mock_get_config.assert_called_once()

    @mock.patch("ansible_base.resource_registry.workload_identity_client.get_resource_server_config")
    def test_factory_passes_kwargs_to_client(self, mock_get_config):
        """Test that factory function passes additional kwargs to client."""
        from ansible_base.resource_registry.workload_identity_client import get_workload_identity_client

        mock_get_config.return_value = {
            "URL": "https://gateway.example.com",
            "VALIDATE_HTTPS": True,
        }

        client = get_workload_identity_client(
            jwt_user_id=123,
            jwt_expiration=120,
            raise_if_bad_request=False,
        )

        assert client.jwt_user_id == "123"  # Converted to string
        assert client.jwt_expiration == 120
        assert client.raise_if_bad_request is False

    @mock.patch("ansible_base.resource_registry.workload_identity_client.get_resource_server_config")
    def test_factory_with_https_disabled(self, mock_get_config):
        """Test that factory respects VALIDATE_HTTPS=False from config."""
        from ansible_base.resource_registry.workload_identity_client import get_workload_identity_client

        mock_get_config.return_value = {
            "URL": "http://localhost:8000",
            "VALIDATE_HTTPS": False,
        }

        client = get_workload_identity_client()

        assert client.base_url == "http://localhost:8000/"
        assert client.verify_https is False
