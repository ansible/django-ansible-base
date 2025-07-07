from django.conf import settings
from rest_framework import authentication

from ansible_base.lib.utils.settings import get_setting


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
        csrf_trusted_origins = settings.CSRF_TRUSTED_ORIGINS
        try:
            # Temporarily patch the setting
            settings.CSRF_TRUSTED_ORIGINS = get_setting("CSRF_TRUSTED_ORIGINS", csrf_trusted_origins)
            return super().enforce_csrf(request)
        finally:
            # Revert setting after this is done
            settings.CSRF_TRUSTED_ORIGINS = csrf_trusted_origins
