from rest_framework import authentication

from ansible_base.lib.utils.settings import replace_trusted_origins


class SessionAuthentication(authentication.SessionAuthentication):
    """
    This class allows us to fail with a 401 if the user is not authenticated.

    Allows CSRF_TRUSTED_ORIGINS to be read dynamically using get_setting.
    Reverting the value of CSRF_TRUSTED_ORIGINS afterwards.
    """

    def authenticate_header(self, request):
        # DRF renders a 401 challenge from its *first* configured
        # authenticator. SessionAuthentication is deliberately first, but a
        # request that supplied Bearer credentials must receive the RFC 6750
        # challenge produced by the Bearer dispatcher instead of ``Session``.
        authorization = request.headers.get("Authorization", "")
        scheme, _, _credential = authorization.partition(" ")
        if scheme.lower() in {"bearer", "token"}:
            # Import lazily to keep session-only installations independent of
            # the optional authentication app and its dispatcher dependencies.
            from ansible_base.authentication.bearer_authentication import BearerAuthentication

            return BearerAuthentication().authenticate_header(request)
        return "Session"

    @replace_trusted_origins
    def enforce_csrf(self, request):
        """
        Enforce CSRF validation for session based authentication using
        AnsibleBaseCsrfViewMiddleware instead of Django's CsrfViewMiddleware.
        """
        return super().enforce_csrf(request)
