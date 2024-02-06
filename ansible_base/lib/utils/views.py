import importlib
import logging
import time

from django.conf import settings
from django.db import connection
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import AuthenticationFailed, ParseError, PermissionDenied, UnsupportedMediaType
from rest_framework.views import APIView

from ansible_base.lib.utils.settings import get_function_from_setting, get_setting

logger = logging.getLogger('ansible_base.lib.utils.views')


class AnsibleBaseView(APIView):
    def initialize_request(self, request, *args, **kwargs):
        """
        Store the Django REST Framework Request object as an attribute on the
        normal Django request, store time the request started.
        """
        self.time_started = time.time()
        if get_setting('SQL_DEBUG', False):
            self.queries_before = len(connection.queries)

        # If there are any custom headers in REMOTE_HOST_HEADERS, make sure
        # they respect the allowed proxy list
        proxy_ip_allowed_list = get_setting('PROXY_IP_ALLOWED_LIST', None)
        if proxy_ip_allowed_list and all(
            [
                request.environ.get('REMOTE_ADDR') not in proxy_ip_allowed_list,
                request.environ.get('REMOTE_HOST') not in proxy_ip_allowed_list,
            ]
        ):
            for custom_header in get_setting('REMOTE_HOST_HEADERS', None):
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

        response['X-API-Product-Name'] = get_setting('ANSIBLE_BASE_PRODUCT_NAME', _('Unnamed'))
        response['X-API-Node'] = get_setting('CLUSTER_HOST_ID', _('Unknown'))

        time_started = getattr(self, 'time_started', None)
        if time_started:
            time_elapsed = time.time() - self.time_started
            response['X-API-Time'] = '%0.3fs' % time_elapsed

        if get_setting('SQL_DEBUG', False):
            queries_before = getattr(self, 'queries_before', 0)
            q_times = [float(q['time']) for q in connection.queries[queries_before:]]
            response['X-API-Query-Count'] = len(q_times)
            response['X-API-Query-Time'] = '%0.3fs' % sum(q_times)

        if getattr(self, 'deprecated', False):
            response['Warning'] = _('This resource has been deprecated and will be removed in a future release.')

        return response


# Determine and load the parent view
# If anything fails in here its a pretty low level exception so we don't catch anything and just let it raise
parent_view = getattr(settings, 'ANSIBLE_BASE_CUSTOM_VIEW_PARENT', None)
parent_view_class = AnsibleBaseView
if parent_view:
    try:
        module_name, junk, class_name = parent_view.rpartition('.')
        logger.debug(f"Trying to import parent view {class_name} from package {module_name}")
        module = importlib.import_module(module_name, package=class_name)
        parent_view_class = getattr(parent_view_class, class_name)
    except ModuleNotFoundError:
        logger.error(f"Failed to find parent view class {parent_view}, defaulting to AnsibleBaseView")
    except ImportError:
        logger.exception(f"Failed to import {parent_view}, defaulting to AnsibleBaseView")


class AnsibleBaseDjanoAppApiView(parent_view_class):
    pass
