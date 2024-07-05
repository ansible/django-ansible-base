# Contains extensions for DRF authenticator classes
import logging

from rest_framework.authentication import BaseAuthentication, CSRFCheck
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger("ansible_base.lib.authentication.authenticators")


class AnsibleBaseAuthentication(BaseAuthentication):
    def enforce_csrf(self, request):
        """
        Enforce CSRF validation for DRF Authenticator
        needs to be called by AnsibleBaseAuthentication.authenticate
        to take effect

        Copied from DRF SessionAuthentication, including the comments
        """

        def dummy_get_response(request):
            return None

        check = CSRFCheck(dummy_get_response)
        # populates request.META['CSRF_COOKIE'], which is used in process_view()
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            # CSRF failed, bail with explicit error message
            logger.error('CSRF Failed: %s' % reason)

            raise PermissionDenied('CSRF Failed: %s' % reason)
