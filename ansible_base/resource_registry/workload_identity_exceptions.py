"""Custom exceptions for workload identity client."""

from rest_framework.exceptions import APIException
from rest_framework.status import HTTP_401_UNAUTHORIZED


class WorkloadIdentityError(APIException):
    """Base exception for workload identity client errors."""

    status_code = HTTP_401_UNAUTHORIZED
    default_detail = "Workload identity operation failed."
    default_code = "workload_identity_error"


class TokenRequestError(WorkloadIdentityError):
    """Raised when token request fails."""

    status_code = HTTP_401_UNAUTHORIZED
    default_detail = "Failed to obtain workload identity token."
    default_code = "token_request_failed"


class ServiceAuthenticationError(WorkloadIdentityError):
    """Raised when service authentication fails."""

    status_code = HTTP_401_UNAUTHORIZED
    default_detail = "Service authentication failed."
    default_code = "service_auth_failed"
