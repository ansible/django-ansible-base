"""Workload Identity API Client.

This client provides functionality to request workload identity tokens
from the workload identity endpoint with service token authentication.
"""

import logging
import time
from typing import Optional

import jwt as pyjwt
import requests

from ansible_base.lib.workload_identity.exceptions import (
    InvalidTokenError,
    ServiceAuthenticationError,
    TokenRequestError,
)
from ansible_base.lib.workload_identity.types import (
    WorkloadIdentityTokenRequest,
    WorkloadIdentityTokenResponse,
)
from ansible_base.resource_registry.resource_server import get_resource_server_config, get_service_token

logger = logging.getLogger("ansible_base.lib.workload_identity.client")


class WorkloadIdentityClient:
    """
    Client for requesting workload identity tokens.

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
        jwt_user_id: Optional[int] = None,
        jwt_expiration: int = 60,
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
        self.base_url = base_url.rstrip("/")
        self.jwt_user_id = jwt_user_id
        self.jwt_expiration = jwt_expiration
        self.verify_https = verify_https
        self.raise_if_bad_request = raise_if_bad_request

        # Token management
        self._jwt: Optional[str] = None
        self._jwt_timeout: Optional[float] = None

    def refresh_jwt(self) -> None:
        """
        Refresh the service token.

        Generates a new service token with the configured expiration.
        Includes a 2-second buffer to account for slower requests.
        """
        try:
            self._jwt_timeout = time.time() + (self.jwt_expiration - 2)
            self._jwt = get_service_token(self.jwt_user_id, expiration=self.jwt_expiration)
            logger.debug("Service token refreshed successfully.")
        except Exception as e:
            logger.error(f"Failed to refresh service token: {e}")
            raise ServiceAuthenticationError(f"Failed to refresh service token: {e}") from e

    @property
    def jwt(self) -> str:
        """
        Get the current service token, refreshing if needed.

        Returns:
            str: Current valid service token

        Raises:
            ServiceAuthenticationError: If token refresh fails
        """
        if self._jwt is None or self._jwt_timeout is None or time.time() >= self._jwt_timeout:
            self.refresh_jwt()
        return self._jwt

    @property
    def service_auth_header(self) -> dict:
        """
        Get the service authentication header.

        Returns:
            dict: Headers dictionary with X-ANSIBLE-SERVICE-AUTH
        """
        return {"X-ANSIBLE-SERVICE-AUTH": self.jwt}

    def _make_request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        """
        Make an HTTP request to the workload identity endpoint.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/api/gateway/v1/workload_identity_tokens")
            data: Request body data (will be sent as JSON)
            headers: Additional headers to include

        Returns:
            requests.Response: HTTP response object

        Raises:
            TokenRequestError: If the request fails and raise_if_bad_request is True
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        logger.info(f"Making {method} request to {url}")

        # Build headers
        request_headers = {**self.service_auth_header}
        if headers:
            request_headers.update(headers)

        # Build request kwargs
        kwargs = {
            "method": method,
            "url": url,
            "headers": request_headers,
            "verify": self.verify_https,
        }

        if data:
            kwargs["json"] = data
            logger.debug(f"Request data: {data}")

        try:
            resp = requests.request(**kwargs)
            logger.debug(f"Response status: {resp.status_code}")

            if self.raise_if_bad_request:
                try:
                    resp.raise_for_status()
                except requests.exceptions.HTTPError as e:
                    content = resp.text
                    logger.error(f"HTTP error: {e}\nResponse content: {content}")
                    raise TokenRequestError(f"{e}\nResponse content: {content}") from e

            return resp

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise TokenRequestError(f"Request failed: {e}") from e

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
            InvalidTokenError: If the returned token is invalid

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

        # Make POST request
        response = self._make_request(
            method="POST",
            path="/api/gateway/v1/workload_identity_tokens",
            data=data,
        )

        # Parse response
        try:
            response_data = response.json()
            logger.debug(f"Response data: {response_data}")
        except Exception as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise TokenRequestError(f"Failed to parse response: {e}") from e

        # Validate access token is present
        if "access_token" not in response_data:
            logger.error("Response missing 'access_token' field")
            raise TokenRequestError("Response missing 'access_token' field")

        access_token = response_data["access_token"]

        # Validate JWT structure (basic check - don't verify signature here)
        try:
            # Decode without verification to check structure
            pyjwt.decode(access_token, options={"verify_signature": False})
            logger.debug("Access token has valid JWT structure")
        except pyjwt.exceptions.DecodeError as e:
            logger.error(f"Invalid JWT token structure: {e}")
            raise InvalidTokenError(f"Invalid JWT token: {e}") from e

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
    """
    config = get_resource_server_config()

    return WorkloadIdentityClient(
        base_url=config["URL"],
        verify_https=config["VALIDATE_HTTPS"],
        **kwargs,
    )
