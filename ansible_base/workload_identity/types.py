"""Type definitions for workload identity client."""

from typing import NamedTuple, Optional


class WorkloadIdentityTokenRequest(NamedTuple):
    """
    Request body for workload identity token endpoint.

    Aligns with the serializer defined in AAP-43414.
    """

    claims: dict
    """Dictionary of claims to include in the workload identity token."""

    scope: str
    """Token scope string (e.g., 'read', 'write', 'read write')."""


class WorkloadIdentityTokenResponse(NamedTuple):
    """Response from workload identity token endpoint."""

    access_token: str
    """The JWT access token."""

    token_type: Optional[str] = "Bearer"
    """Token type, typically 'Bearer'."""

    expires_in: Optional[int] = None
    """Token expiration time in seconds."""

    scope: Optional[str] = None
    """The scope of the token."""
