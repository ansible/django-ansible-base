import logging
import time

from django.conf import settings
from django.db import connection
from django.utils.translation import gettext_lazy as _
from rest_framework import views
from rest_framework.exceptions import AuthenticationFailed, ParseError, PermissionDenied, UnsupportedMediaType

from ansible_base.lib.utils.settings import get_function_from_setting

logger = logging.getLogger('ansible_base.lib.utils.views')


class AnsibleBaseView(views.APIView):
    def initialize_request(self, request, *args, **kwargs):
        """
        Store the Django REST Framework Request object as an attribute on the
        normal Django request, store time the request started.
        """
        self.time_started = time.time()
        if getattr(settings, 'SQL_DEBUG', False):
            self.queries_before = len(connection.queries)

        # If there are any custom headers in REMOTE_HOST_HEADERS, make sure
        # they respect the allowed proxy list
        if all(
            [
                settings.PROXY_IP_ALLOWED_LIST,
                request.environ.get('REMOTE_ADDR') not in settings.PROXY_IP_ALLOWED_LIST,
                request.environ.get('REMOTE_HOST') not in settings.PROXY_IP_ALLOWED_LIST,
            ]
        ):
            for custom_header in settings.REMOTE_HOST_HEADERS:
                if custom_header.startswith('HTTP_'):
                    request.environ.pop(custom_header, None)

        drf_request = super().initialize_request(request, *args, **kwargs)
        request.drf_request = drf_request
        try:
            request.drf_request_user = getattr(drf_request, 'user', False)
        except AuthenticationFailed:
            request.drf_request_user = None
        except (PermissionDenied, ParseError) as exc:
            request.drf_request_user = None
            self.__init_request_error__ = exc
        except UnsupportedMediaType as exc:
            exc.detail = _(
                'You did not use correct Content-Type in your HTTP request. If you are using our REST API, the Content-Type must be application/json'
            )
            self.__init_request_error__ = exc
        return drf_request

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        if request.user.is_authenticated:
            version = 'Unknown'
            try:
                the_function = get_function_from_setting('ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION')
                version = the_function()
            except Exception:
                logger.exception(_('ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION was set but calling it as a function failed (see exception).'))

            response['X-API-Product-Version'] = version

        response['X-API-Product-Name'] = getattr(settings, 'ANSIBLE_BASE_PRODUCT_NAME', _('Unnamed'))
        response['X-API-Node'] = getattr(settings, 'CLUSTER_HOST_ID', _('Unknown'))

        time_started = getattr(self, 'time_started', None)
        if time_started:
            time_elapsed = time.time() - self.time_started
            response['X-API-Time'] = '%0.3fs' % time_elapsed

        if getattr(settings, 'SQL_DEBUG', False):
            queries_before = getattr(self, 'queries_before', 0)
            q_times = [float(q['time']) for q in connection.queries[queries_before:]]
            response['X-API-Query-Count'] = len(q_times)
            response['X-API-Query-Time'] = '%0.3fs' % sum(q_times)

        if getattr(self, 'deprecated', False):
            response['Warning'] = _('This resource has been deprecated and will be removed in a future release.')

        return response
