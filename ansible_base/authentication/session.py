from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    """
    This class allows us to fail with a 401 if the user is not authenticated.
    """

    def authenticate_header(self, request):
        return "Session"
