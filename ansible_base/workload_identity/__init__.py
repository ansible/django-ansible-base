"""
Workload Identity Client Package.

This package provides a client for requesting workload identity tokens
from the Ansible Gateway service using service token authentication.
"""

from ansible_base.workload_identity.client import WorkloadIdentityClient, get_workload_identity_client
from ansible_base.workload_identity.exceptions import (
    InvalidTokenError,
    ServiceAuthenticationError,
    TokenRequestError,
    WorkloadIdentityError,
)
from ansible_base.workload_identity.types import (
    WorkloadIdentityTokenRequest,
    WorkloadIdentityTokenResponse,
)

__all__ = [
    "WorkloadIdentityClient",
    "get_workload_identity_client",
    "WorkloadIdentityError",
    "InvalidTokenError",
    "TokenRequestError",
    "ServiceAuthenticationError",
    "WorkloadIdentityTokenRequest",
    "WorkloadIdentityTokenResponse",
]
