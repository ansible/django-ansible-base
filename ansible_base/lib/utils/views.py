import logging

from django.conf import settings
from rest_framework import views

logger = logging.getLogger('ansible_base.lib.utils.views')


setting = 'ANSIBLE_BASE_EXTRA_HEADERS'


class ViewWithHeaders(views.APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        for name, value in getattr(settings, setting, {}).items():
            if isinstance(name, str) and isinstance(value, str):
                response[name] = value
            else:
                logger.error(f"When adding a custom header expected (str,str) but got ({type(name)}, {type(value)}) please check your {setting} settings")

        return response
