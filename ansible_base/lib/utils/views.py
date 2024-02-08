import importlib
import logging
import time

from django.conf import settings
from django.utils.translation import gettext_lazy as _
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

        return super().initialize_request(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        if request.user and request.user.is_authenticated:
            version = 'Unknown'
            setting = 'ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION'
            the_function = None
            try:
                the_function = get_function_from_setting(setting)
            except Exception:
                logger.exception(_('Failed to load function from {setting} (see exception)'.format(setting=setting)))

            if the_function:
                try:
                    version = the_function()
                except Exception:
                    logger.exception(_('{setting} was set but calling it as a function failed (see exception).'.format(setting=setting)))

            response['X-API-Product-Version'] = version

        response['X-API-Product-Name'] = get_setting('ANSIBLE_BASE_PRODUCT_NAME', _('Unnamed'))
        response['X-API-Node'] = get_setting('CLUSTER_HOST_ID', _('Unknown'))

        time_started = getattr(self, 'time_started', None)
        if time_started:
            time_elapsed = time.time() - self.time_started
            response['X-API-Time'] = '%0.3fs' % time_elapsed

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
        if not module_name or not class_name:
            logger.error("ANSIBLE_BASE_CUSTOM_VIEW_PARENT must be in the format package.subpackage.view, defaulting to AnsibleBaseView")
        else:
            module = importlib.import_module(module_name, package=class_name)
            parent_view_class = getattr(module, class_name)
    except ModuleNotFoundError:
        logger.error(f"Failed to find parent view class {parent_view}, defaulting to AnsibleBaseView")
    except ImportError:
        logger.exception(f"Failed to import {parent_view}, defaulting to AnsibleBaseView")


class AnsibleBaseDjanoAppApiView(parent_view_class):
    pass
