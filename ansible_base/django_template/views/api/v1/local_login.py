import json
import logging
import re

from django.contrib.auth import views
from django.core.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.exceptions import NotAcceptable
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.renderers import StaticHTMLRenderer
from rest_framework.response import Response
from social_core.exceptions import AuthException

from ansible_base.lib.utils.requests import get_remote_host
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.django_template.views.local_login')


class LoggedLoginView(views.LoginView):
    def get(self, request, *args, **kwargs):
        # The django.auth.contrib login form doesn't perform the content
        # negotiation we've come to expect from DRF; add in code to catch
        # situations where Accept != text/html (or */*) and reply with
        # an HTTP 406
        try:
            DefaultContentNegotiation().select_renderer(request, [StaticHTMLRenderer], 'html')
        except NotAcceptable:
            resp = Response(data=json.dumps({"details": "Unacceptable content type"}), status=status.HTTP_406_NOT_ACCEPTABLE)
            resp.accepted_renderer = StaticHTMLRenderer()
            resp.accepted_media_type = 'text/plain'
            resp.content_type = 'application/json'
            resp.renderer_context = {}
            return resp
        return super(LoggedLoginView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        try:
            ret = super(LoggedLoginView, self).post(request, *args, **kwargs)
        except AuthException as e:
            # Log a warning when an exception occurs during login,
            # particularly when SYSTEM_USERNAME attempts to log in.
            logger.warning("Exception occurred during login.")
            raise PermissionDenied from e

        if request.user.is_authenticated:
            logger.info(f"User {self.request.user.username} logged in from {get_remote_host(request)}")
            return ret
        else:
            if 'username' in self.request.POST:
                username = self.request.POST.get('username')
                # Maybe we want to scale this in the future to support additional characters
                if not re.match('^[A-Za-z0-9@._-]+$', username):
                    from base64 import b64encode

                    username = f"(base64) {b64encode(username.encode('UTF-8'))}"
                logger.warning(f"Login failed for user {username} from {get_remote_host(request)}")
            ret.status_code = 401
            return ret


@method_decorator(require_http_methods(["POST", "GET"]), name="dispatch")
class LoggedLogoutView(views.LogoutView):

    success_url_allowed_hosts = get_setting('LOGOUT_ALLOWED_HOSTS', [])

    def dispatch(self, request, *args, **kwargs):
        original_user = getattr(request, 'user', None)
        ret = super().dispatch(request, *args, **kwargs)
        current_user = getattr(request, 'user', None)
        if (not current_user or not getattr(current_user, 'pk', True)) and current_user != original_user:
            logger.info("User {} logged out.".format(original_user.username))
        return ret
