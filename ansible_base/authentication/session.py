from rest_framework import authentication

from ansible_base.lib.utils.settings import replace_trusted_origins


class SessionAuthentication(authentication.SessionAuthentication):
    """
    This class allows us to fail with a 401 if the user is not authenticated.

    Allows CSRF_TRUSTED_ORIGINS to be read dynamically using get_setting.
    Reverting the value of CSRF_TRUSTED_ORIGINS afterwards.
    """

    def authenticate_header(self, request):
        return "Session"

    @replace_trusted_origins
    def enforce_csrf(self, request):
        """
        Enforce CSRF validation for session based authentication using
        AnsibleBaseCsrfViewMiddleware instead of Django's CsrfViewMiddleware.
        """
        return super().enforce_csrf(request)
