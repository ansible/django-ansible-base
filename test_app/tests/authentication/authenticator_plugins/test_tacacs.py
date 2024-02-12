from unittest import mock

from django.urls import reverse

from ansible_base.authentication.session import SessionAuthentication

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.tacacs.AuthenticatorPlugin.authenticate")
def test_tacacs_auth_successful(authenticate, unauthenticated_api_client, tacacs_authenticator, user):
    """
    Test that a successful TACACS authentication returns a 200 on the /me endpoint.

    Here we mock the TACACS authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    did_login = client.login()
    assert did_login, "Failed to login"

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.tacacs.AuthenticatorPlugin.authenticate")
def test_tacacs_auth_failure(authenticate, unauthenticated_api_client, tacacs_authenticator):
    """
    Test that a failed tacacs authentication returns a 401 on the /me endpoint.

    Here we mock the tacacs authentication backend to return None.
    """
    client = unauthenticated_api_client
    authenticate.return_value = None
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
def test_tacacsplus_settings(get, put, patch, admin):
    url = reverse('api:setting_singleton_detail', kwargs={'name': 'tacacsplus'})
    response = get(url, user=admin, expect=200)
    put(url, user=admin, data=response.data, expect=200)
    patch(url, user=admin, data={'SECRET': 'mysecret'}, expect=200)
    patch(url, user=admin, data={'SECRET': ''}, expect=200)
    patch(url, user=admin, data={'HOST': 'localhost'}, expect=400)
    patch(url, user=admin, data={'SECRET': 'mysecret'}, expect=200)
    patch(url, user=admin, data={'HOST': 'localhost'}, expect=200)
    patch(url, user=admin, data={'HOST': '', 'SECRET': ''}, expect=200)
    patch(url, user=admin, data={'HOST': 'localhost', 'SECRET': ''}, expect=400)
    patch(url, user=admin, data={'HOST': 'localhost', 'SECRET': 'mysecret'}, expect=200)
