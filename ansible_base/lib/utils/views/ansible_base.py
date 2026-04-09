import logging
import time

from django.utils.translation import gettext_lazy as _
from rest_framework.views import APIView

from ansible_base.lib.utils.settings import get_function_from_setting, get_setting

logger = logging.getLogger('ansible_base.lib.utils.views.ansible_base')


class AnsibleBaseView(APIView):

    ordering = ['pk']

    # pulp openapi generator compatibility
    endpoint_name = ''

    # pulp openapi generator compatibility
    @classmethod
    def endpoint_pieces(cls):
        return []

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
            version = _('Unknown')
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

    def extra_related_fields(self, obj):
        """
        A hook for adding extra related fields to serializers which
        make use of this view/viewset.

        This is particularly useful for mixins which want to extend a viewset
        with additional actions and provide those actions as related fields.
        """
        return {}
