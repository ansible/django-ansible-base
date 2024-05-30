from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.urls import reverse
from pyrad.client import Timeout
from pyrad.packet import AccessAccept, AccessReject, AccessRequest

from ansible_base.authentication.authenticator_plugins._radiusauth import RADIUSBackend as BaseRADIUSBackend
from ansible_base.authentication.authenticator_plugins._radiusauth import RADIUSRealmBackend
from ansible_base.authentication.authenticator_plugins.radius import AuthenticatorPlugin, RADIUSBackend, RADIUSUser
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.session import SessionAuthentication
from test_app.models import User

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.radius.AuthenticatorPlugin.authenticate")
def test_oidc_auth_successful(authenticate, unauthenticated_api_client, radius_authenticator, user):
    """
    Test that a successful RADIUS authentication returns a 200 on the /me endpoint.

    Here we mock the RADIUS authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.radius.AuthenticatorPlugin.authenticate", return_value=None)
def test_oidc_auth_failed(authenticate, unauthenticated_api_client, radius_authenticator):
    """
    Test that a failed RADIUS authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.radius.RADIUSBackend")
def test_authenticator_plugin(backend_cls, unauthenticated_api_client, radius_configuration, radius_authenticator, randname):
    """
    Test RADIUS authenticator logic.

    Test that the RADIUS backend is created with the correct settings.
    Test that login credentials are passed to the backend's authenticate() method call.
    Test that associated AuthenticatorUser record is created.
    """

    # Login with random info so the local authenticator won't auth the user if its configured
    random_password = randname("radius_password")
    random_username = randname("user")

    backend = backend_cls.return_value
    backend.authenticate.return_value = RADIUSUser(
        username=random_username,
        groups=["users", "managers"],
        is_staff=False,
        is_superuser=False,
    )

    client = unauthenticated_api_client
    client.login(username=random_username, password=random_password)

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200

    backend_settings = backend_cls.call_args[0][0]
    assert vars(backend_settings) == {
        "RADIUS_SERVER": radius_configuration["SERVER"],
        "RADIUS_PORT": radius_configuration["PORT"],
        "RADIUS_SECRET": radius_configuration["SECRET"],
    }
    backend.authenticate.called_once_with(username=random_username, password=random_password)
    assert AuthenticatorUser.objects.filter(uid=random_username, provider=radius_authenticator).exists()
    assert User.objects.filter(username=random_username).exists()


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.radius.RADIUSBackend")
def test_authenticator_plugin_failed(backend_cls, unauthenticated_api_client, radius_configuration, radius_authenticator, user):
    """
    Test RADIUS authenticator logic if user or password is invalid.
    """
    backend = backend_cls.return_value
    backend.authenticate.return_value = None

    client = unauthenticated_api_client
    client.login(username="invalid", password="password")

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401

    assert not AuthenticatorUser.objects.filter(uid="invalid", provider=radius_authenticator).exists()


class MockReply(dict):
    def __init__(self, code, data):
        super().__init__(data)
        self.code = code


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins._radiusauth.Client")
def test_base_radius_backend(pyrad_client_cls):
    client = pyrad_client_cls.return_value

    auth_packet = client.CreateAuthPacket.return_value
    reply = MockReply(
        AccessAccept,
        {
            'Class': [
                b'group=testgroup',
                b'role=staff',
                b'role=superuser',
            ]
        },
    )
    client.SendPacket.return_value = reply

    url = reverse(authenticated_test_page)
    requeest_factory = RequestFactory()
    request = requeest_factory.get(url)

    Group.objects.create(name="testgroup")

    settings = SimpleNamespace(RADIUS_SERVER='localhost', RADIUS_PORT=1812, RADIUS_SECRET="secret")
    backend = BaseRADIUSBackend(settings)
    user = backend.authenticate(request, username="user", password="password")

    assert user is not None
    assert isinstance(user, User)
    assert user.username == "user"
    assert user.is_staff
    assert user.is_superuser

    user_groups = user.groups.all()
    assert len(user_groups) == 1
    assert user_groups[0].name == "testgroup"

    client.CreateAuthPacket.assert_called_with(code=AccessRequest, User_Name="user")
    client.SendPacket.assert_called_once_with(auth_packet)


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins._radiusauth.Client")
def test_radius_realm_backend(pyrad_client_cls):
    client = pyrad_client_cls.return_value

    auth_packet = client.CreateAuthPacket.return_value
    reply = MockReply(
        AccessAccept,
        {
            'Class': [
                b'group=testgroup',
                b'role=staff',
                b'role=superuser',
            ]
        },
    )
    client.SendPacket.return_value = reply

    url = reverse(authenticated_test_page)
    requeest_factory = RequestFactory()
    request = requeest_factory.get(url)

    Group.objects.create(name="testgroup")

    settings = SimpleNamespace(RADIUS_SERVER='localhost', RADIUS_PORT=1812, RADIUS_SECRET="secret")
    backend = RADIUSRealmBackend(settings)
    user = backend.authenticate(request, username="user", password="password", realm="testrealm1")

    assert user is not None
    assert isinstance(user, User)
    assert user.username == "user@testrealm1"
    assert user.is_staff
    assert user.is_superuser

    user_groups = user.groups.all()
    assert len(user_groups) == 1
    assert user_groups[0].name == "testgroup"

    client.CreateAuthPacket.assert_called_with(code=AccessRequest, User_Name="user")
    client.SendPacket.assert_called_once_with(auth_packet)


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins._radiusauth.Client")
def test_radius_backend(pyrad_client_cls):
    client = pyrad_client_cls.return_value

    auth_packet = client.CreateAuthPacket.return_value
    reply = MockReply(
        AccessAccept,
        {
            'Class': [
                b'group=supervisors',
                b'group=developers',
            ]
        },
    )
    client.SendPacket.return_value = reply

    url = reverse(authenticated_test_page)
    requeest_factory = RequestFactory()
    request = requeest_factory.get(url)

    settings = SimpleNamespace(RADIUS_SERVER='localhost', RADIUS_PORT=1812, RADIUS_SECRET="secret")
    backend = RADIUSBackend(settings)
    radius_user = backend.authenticate(request, username="user", password="password")

    assert radius_user is not None
    assert radius_user == RADIUSUser(
        username="user",
        groups=["supervisors", "developers"],
        is_staff=False,
        is_superuser=False,
    )

    client.CreateAuthPacket.assert_called_with(code=AccessRequest, User_Name="user")
    client.SendPacket.assert_called_once_with(auth_packet)


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins._radiusauth.Client")
def test_radius_backend_access_reject(pyrad_client_cls):
    client = pyrad_client_cls.return_value

    auth_packet = client.CreateAuthPacket.return_value
    client.SendPacket.return_value.code = AccessReject

    url = reverse(authenticated_test_page)
    requeest_factory = RequestFactory()
    request = requeest_factory.get(url)

    settings = SimpleNamespace(RADIUS_SERVER='localhost', RADIUS_PORT=1812, RADIUS_SECRET="secret")
    backend = RADIUSBackend(settings)
    radius_user = backend.authenticate(request, username="user", password="invalid")

    assert radius_user is None

    client.CreateAuthPacket.assert_called_with(code=AccessRequest, User_Name="user")
    client.SendPacket.assert_called_once_with(auth_packet)


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins._radiusauth.Client")
def test_radius_backend_access_timeout(pyrad_client_cls):
    client = pyrad_client_cls.return_value

    auth_packet = client.CreateAuthPacket.return_value
    client.SendPacket.side_effect = Timeout

    url = reverse(authenticated_test_page)
    requeest_factory = RequestFactory()
    request = requeest_factory.get(url)

    settings = SimpleNamespace(RADIUS_SERVER='localhost', RADIUS_PORT=1812, RADIUS_SECRET="secret")
    backend = RADIUSBackend(settings)
    radius_user = backend.authenticate(request, username="user", password="invalid")

    assert radius_user is None

    client.CreateAuthPacket.assert_called_with(code=AccessRequest, User_Name="user")
    client.SendPacket.assert_called_once_with(auth_packet)


def test_radius_authenticate_returns_none_if_no_username_or_password_is_set():
    radius_plugin = AuthenticatorPlugin()
    requeest_factory = RequestFactory()
    get_request = requeest_factory.get('/api')
    assert radius_plugin.authenticate(get_request, username=None) is None
    assert radius_plugin.authenticate(get_request, password=None) is None
