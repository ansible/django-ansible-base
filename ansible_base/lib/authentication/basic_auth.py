import logging

from ansible_base.lib.utils.settings import get_setting
from django.utils.encoding import smart_str
from rest_framework import authentication

logger = logging.getLogger('dab.lib.authentication.basic_auth')


class LoggedBasicAuthentication(authentication.BasicAuthentication):
    def authenticate(self, request):
        if not get_setting('ANSIBLE_BASE_BASIC_AUTH_ENABLED', False):
            return
        ret = super(LoggedBasicAuthentication, self).authenticate(request)
        if ret:
            username = ret[0].username if ret[0] else '<none>'
            logger.info(smart_str(f"User {username} performed a {request.method} to {request.path} through the API via basic auth"))
        return ret

    def authenticate_header(self, request):
        if not get_setting('ANSIBLE_BASE_BASIC_AUTH_ENABLED'):
            return
        return super(LoggedBasicAuthentication, self).authenticate_header(request)
