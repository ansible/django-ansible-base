from rest_framework import authentication, exceptions

from ansible_base.authentication.middleware import (
    AnsibleBaseCsrfViewMiddleware,
)


class AnsibleBaseCSRFCheck(AnsibleBaseCsrfViewMiddleware):
    """
    Custom CSRF check class that uses AnsibleBaseCsrfViewMiddleware
    instead of Django's CsrfViewMiddleware for CSRF validation.

    This ensures that CSRF_TRUSTED_ORIGINS is read using get_setting
    instead of directly from Django settings.
    """

    def _reject(self, request, reason):
        # Return the failure reason instead of an HttpResponse
        return reason


class SessionAuthentication(authentication.SessionAuthentication):
    """
    This class allows us to fail with a 401 if the user is not authenticated.

    Uses AnsibleBaseCsrfViewMiddleware for CSRF checking instead of Django's
    default CsrfViewMiddleware, allowing CSRF_TRUSTED_ORIGINS to be read
    dynamically using get_setting.
    """

    def authenticate_header(self, request):
        return "Session"

    def enforce_csrf(self, request):
        """
        Enforce CSRF validation for session based authentication using
        AnsibleBaseCsrfViewMiddleware instead of Django's CsrfViewMiddleware.
        """

        def dummy_get_response(request):  # pragma: no cover
            return None

        check = AnsibleBaseCSRFCheck(dummy_get_response)
        # populates request.META['CSRF_COOKIE'], which is used in process_view()
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            # CSRF failed, bail with explicit error message
            raise exceptions.PermissionDenied('CSRF Failed: %s' % reason)
