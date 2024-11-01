from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    def authenticate_header(self, request):
        return 'Session'
