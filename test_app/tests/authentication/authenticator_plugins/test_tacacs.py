import logging
from collections import OrderedDict
from unittest import mock
from unittest.mock import MagicMock

import pytest
import tacacs_plus
from django.urls import reverse
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.tacacs import AuthenticatorPlugin, TacacsConfiguration
from ansible_base.authentication.session import SessionAuthentication

authenticated_test_page = "authenticator-list"

@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.tacacs.AuthenticatorPlugin.authenticate")
def test_tacacs_auth_successful(authenticate, unauthenticated_api_client, AuthenticatorPlugin, user):
    """
    Test that a successful TACACS authentication returns a 200 on the /me endpoint.

    Here we mock the TACACS authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200
