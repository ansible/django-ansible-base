"""Workload Identity API Client.

This client provides functionality to request workload identity tokens
from the Gateway workload identity endpoint with service token authentication.
"""

import logging

import requests

from ansible_base.resource_registry.resource_server import get_resource_server_config
from ansible_base.resource_registry.service_client import BaseServiceClient
from ansible_base.resource_registry.workload_identity_exceptions import (
    ServiceAuthenticationError,
    TokenRequestError,
)
from ansible_base.resource_registry.workload_identity_types import (
    WorkloadIdentityTokenRequest,
    WorkloadIdentityTokenResponse,
)

logger = logging.getLogger("ansible_base.resource_registry.workload_identity_client")


class WorkloadIdentityClient(BaseServiceClient):
    """
    Client for requesting workload identity tokens from Gateway.

    This client authenticates using service tokens via the X-ANSIBLE-SERVICE-AUTH
    header and makes POST requests to the workload identity tokens endpoint.

    Example:
        >>> client = WorkloadIdentityClient(
        ...     base_url="https://gateway.example.com",
        ...     jwt_user_id=1,
        ...     jwt_expiration=60
        ... )
        >>> response = client.request_token(
        ...     claims={"sub": "user123", "aud": "my-service"},
        ...     scope="read write"
        ... )
        >>> print(response.access_token)
    """

    def __init__(
        self,
        base_url: str,
        jwt_user_id=None,
        jwt_expiration=60,
        verify_https: bool = True,
        raise_if_bad_request: bool = True,
    ):
        """
        Initialize the workload identity client.

        Args:
            base_url: Base URL of the gateway service (e.g., "https://gateway.example.com")
            jwt_user_id: User ID to include in service token (optional)
            jwt_expiration: Service token expiration time in seconds (default: 60)
            verify_https: Whether to verify HTTPS certificates (default: True)
            raise_if_bad_request: Whether to raise exceptions on HTTP errors (default: True)
        """
        # Convert jwt_user_id to string before passing to parent
        # (parent's type hint requires Optional[str], but users may pass int)
        if jwt_user_id is not None:
            jwt_user_id = str(jwt_user_id)

        super().__init__(
            base_url=base_url,
            verify_https=verify_https,
            raise_if_bad_request=raise_if_bad_request,
            jwt_user_id=jwt_user_id,
            jwt_expiration=jwt_expiration,
        )

    def refresh_jwt(self) -> None:
        """
        Refresh the service token with error handling.

        Overrides BaseServiceClient.refresh_jwt() to wrap errors in ServiceAuthenticationError.

        Raises:
            ServiceAuthenticationError: If token refresh fails
        """
        try:
            super().refresh_jwt()
        except Exception as e:
            logger.error(f"Failed to refresh service token: {e}")
            raise ServiceAuthenticationError(f"Failed to refresh service token: {e}") from e

    @property
    def service_auth_header(self) -> dict:
        """
        Get the service authentication headers.

        Returns:
            dict: Dictionary with X-ANSIBLE-SERVICE-AUTH key and JWT token value
        """
        return self.requests_auth_kwargs["headers"]

    def request_token(
        self,
        claims: dict,
        scope: str,
    ) -> WorkloadIdentityTokenResponse:
        """
        Request a workload identity token.

        Makes a POST request to /api/gateway/v1/workload_identity_tokens
        with the specified claims and scope.

        Args:
            claims: Dictionary of claims to include in the token
            scope: Token scope string (e.g., 'read', 'write', 'read write')

        Returns:
            WorkloadIdentityTokenResponse: Token response with access_token

        Raises:
            TokenRequestError: If the request fails

        Example:
            >>> response = client.request_token(
            ...     claims={"sub": "user123", "aud": "my-service"},
            ...     scope="read write"
            ... )
        """
        # Create request body
        request_body = WorkloadIdentityTokenRequest(claims=claims, scope=scope)
        data = request_body._asdict()

        logger.info(f"Requesting workload identity token with scope: {scope}")
        logger.debug(f"Claims: {claims}")

        # Make POST request with error handling
        try:
            response = self._make_request(
                method="POST",
                path="/api/gateway/v1/workload_identity_tokens",
                data=data,
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise TokenRequestError(f"Request failed: {e}") from e

        # Parse response
        try:
            response_data = response.json()
            logger.debug(f"Response data: {response_data}")
        except (requests.exceptions.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise TokenRequestError(f"Failed to parse response: {e}") from e

        # Validate access token is present
        if "access_token" not in response_data:
            logger.error("Response missing 'access_token' field")
            raise TokenRequestError("Response missing 'access_token' field")

        access_token = response_data["access_token"]

        # Create response object
        return WorkloadIdentityTokenResponse(
            access_token=access_token,
            token_type=response_data.get("token_type", "Bearer"),
            expires_in=response_data.get("expires_in"),
            scope=response_data.get("scope", scope),
        )


def get_workload_identity_client(**kwargs) -> WorkloadIdentityClient:
    """
    Get a WorkloadIdentityClient configured from resource server settings.

    This factory function creates a client using the RESOURCE_SERVER configuration,
    similar to get_resource_server_client() in rest_client.py.

    Args:
        **kwargs: Additional arguments passed to WorkloadIdentityClient

    Returns:
        WorkloadIdentityClient: Configured client instance

    Example:
        >>> client = get_workload_identity_client(jwt_user_id=1)
        >>> response = client.request_token(
        ...     claims={"sub": "user123"},
        ...     scope="read"
        ... )
    """
    config = get_resource_server_config()

    return WorkloadIdentityClient(
        base_url=config["URL"],
        verify_https=config["VALIDATE_HTTPS"],
        **kwargs,
    )
