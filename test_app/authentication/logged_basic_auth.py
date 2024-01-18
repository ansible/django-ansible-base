import logging

from django.utils.encoding import smart_str
from rest_framework import authentication

logger = logging.getLogger('test_app.authentication.logged_basic_auth')


class LoggedBasicAuthentication(authentication.BasicAuthentication):
    def authenticate(self, request):
        ret = super(LoggedBasicAuthentication, self).authenticate(request)
        if ret:
            username = ret[0].username if ret[0] else '<none>'
            logger.info(smart_str(f"User {username} performed a {request.method} to {request.path} through the API via basic auth"))
        return ret

    def authenticate_header(self, request):
        return super(LoggedBasicAuthentication, self).authenticate_header(request)


# NOTE: This file is common to many of the services and will allow DRF to return a 401 instead of a 403 on failed login.
#       This is the expected behavior we want so we need this file in test_app to mimic other applications
