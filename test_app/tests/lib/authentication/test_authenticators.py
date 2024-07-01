import pytest
from django.conf import settings
from django.middleware.csrf import _get_new_csrf_string, _mask_cipher_secret
from django.test.client import RequestFactory
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.authentication.authenticators import AnsibleBaseAuthentication


class TestAnsibleBaseAuthentication:
    def test_csrf_enforce_enforces(self):
        rf = RequestFactory()
        authenication = AnsibleBaseAuthentication()
        csrf_secret = _get_new_csrf_string()
        data = {
            "csrfmiddlewaretoken": _mask_cipher_secret(csrf_secret),
        }

        # Create a POST request for any endpoint
        request = rf.post("/api/gateway/v1/tokens", data)
        request.COOKIES[settings.CSRF_COOKIE_NAME] = csrf_secret

        # Fail if PermissionDenied
        authenication.enforce_csrf(request)

        # Make CSRF params bad by making the field token invalid
        request = rf.post("/api/gateway/v1/tokens", data)
        request.COOKIES[settings.CSRF_COOKIE_NAME] = _get_new_csrf_string()

        # Fail if not Permission Denied
        with pytest.raises(PermissionDenied):
            authenication.enforce_csrf(request)
