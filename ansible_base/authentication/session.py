from django.conf import settings
from rest_framework import authentication

from ansible_base.authentication.challenge import ChallengeAwareAuthenticationMixin
from ansible_base.lib.utils.settings import replace_trusted_origins


class SessionAuthentication(ChallengeAwareAuthenticationMixin, authentication.SessionAuthentication):
    """
    This class allows us to fail with a 401 if the user is not authenticated.

    Allows CSRF_TRUSTED_ORIGINS to be read dynamically using get_setting.
    Reverting the value of CSRF_TRUSTED_ORIGINS afterwards.
    """

    def authenticate(self, request):
        if request.COOKIES.get(settings.SESSION_COOKIE_NAME):
            self.record_authentication_challenge(request, "Session")
        return super().authenticate(request)

    def get_default_authentication_challenge(self, request):
        return "Session"

    @replace_trusted_origins
    def enforce_csrf(self, request):
        """
        Enforce CSRF validation for session based authentication using
        AnsibleBaseCsrfViewMiddleware instead of Django's CsrfViewMiddleware.
        """
        return super().enforce_csrf(request)
