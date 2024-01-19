from unittest import mock

import pytest
from django.urls import reverse

from ansible_base.authentication.session import SessionAuthentication
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.saml.AuthenticatorPlugin.authenticate")
def test_saml_auth_successful(authenticate, unauthenticated_api_client, saml_authenticator, user):
    """
    Test that a successful SAML authentication returns a 200 on the /me endpoint.

    Here we mock the SAML authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.parametrize(
    "setting_override, expected_errors",
    [
        pytest.param({}, {}, id="no errors"),
        pytest.param(
            {"SP_PRIVATE_KEY": ENCRYPTED_STRING}, {"SP_PRIVATE_KEY": f"Can not be set to {ENCRYPTED_STRING}"}, id="SP_PRIVATE_KEY is encrypted string"
        ),
        pytest.param({"SP_PRIVATE_KEY": "really invalid"}, {"SP_PRIVATE_KEY": "Unable to load as PEM data"}, id="SP_PRIVATE_KEY is utterly invalid"),
        pytest.param(
            {"IDP_ATTR_USERNAME": None, "IDP_ATTR_USER_PERMANENT_ID": None},
            {"IDP_ATTR_USERNAME": "Either IDP_ATTR_USERNAME or IDP_ATTR_USER_PERMANENT_ID needs to be set"},
            id="null IDP_ATTR_USERNAME and IDP_ATTR_USER_PERMANENT_ID",
        ),
        pytest.param(
            {"IDP_ATTR_USERNAME": "", "IDP_ATTR_USER_PERMANENT_ID": ""},
            {"IDP_ATTR_USERNAME": "This field may not be blank.", "IDP_ATTR_USER_PERMANENT_ID": "This field may not be blank."},
            id="blank IDP_ATTR_USERNAME and IDP_ATTR_USER_PERMANENT_ID",
        ),
        pytest.param(
            {"IDP_ATTR_USERNAME": False, "IDP_ATTR_USER_PERMANENT_ID": False},
            {"IDP_ATTR_USERNAME": "Not a valid string.", "IDP_ATTR_USER_PERMANENT_ID": "Not a valid string."},
            id="false IDP_ATTR_USERNAME and IDP_ATTR_USER_PERMANENT_ID",
        ),
        pytest.param(
            {"-IDP_ATTR_USERNAME": None, "-IDP_ATTR_USER_PERMANENT_ID": None},
            {"IDP_ATTR_USERNAME": "Either IDP_ATTR_USERNAME or IDP_ATTR_USER_PERMANENT_ID needs to be set"},
            id="missing IDP_ATTR_USERNAME and IDP_ATTR_USER_PERMANENT_ID",
        ),
    ],
)
def test_saml_create_authenticator_error_handling(
    admin_api_client,
    saml_configuration,
    setting_override,
    expected_errors,
    shut_up_logging,
):
    """
    Tests various error conditions that arise when validating the configuration of a SAML authenticator.
    """
    for key, value in setting_override.items():
        if key.startswith("-"):
            del saml_configuration[key[1:]]
        else:
            saml_configuration[key] = value

    url = reverse("authenticator-list")
    data = {
        "name": "SAML authenticator (should not get created)",
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "configuration": saml_configuration,
        "type": "ansible_base.authentication.authenticator_plugins.saml",
    }
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400 if expected_errors else 201
    if expected_errors:
        for key, value in expected_errors.items():
            assert key in response.data
            if type(response.data[key]) is dict:
                for sub_key in response.data[key]:
                    assert value[sub_key] in response.data[key][sub_key]
            elif type(response.data[key]) is list:
                assert any(value in item for item in response.data[key]), response.data
            else:
                assert value in response.data[key]


def test_saml_create_authenticator_does_not_leak_private_key_on_error(
    admin_api_client,
    saml_configuration,
    shut_up_logging,
):
    """
    Tests that the private key is not leaked in an error response when creating a SAML authenticator.
    """
    url = reverse("authenticator-list")
    saml_configuration["SP_PRIVATE_KEY"] = "not a real private key"
    data = {
        "name": "SAML authenticator (should not get created)",
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "configuration": saml_configuration,
        "type": "ansible_base.authentication.authenticator_plugins.saml",
    }
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400
    assert "not a real private key" not in str(response.data)


def test_saml_create_authenticator_does_not_leak_private_key_on_success(
    admin_api_client,
    saml_configuration,
    shut_up_logging,
):
    """
    Tests that the private key is not leaked in a success response when creating a SAML authenticator.
    """
    url = reverse("authenticator-list")
    data = {
        "name": "SAML authenticator",
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "configuration": saml_configuration,
        "type": "ansible_base.authentication.authenticator_plugins.saml",
    }
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201
    assert response.data["configuration"]["SP_PRIVATE_KEY"] == ENCRYPTED_STRING


def test_saml_create_authenticator_errors_with_cert_key_mismatch(
    admin_api_client,
    saml_configuration,
    rsa_keypair_with_cert_1,
):
    """
    Tests that the private key is not leaked in an error response when creating a SAML authenticator.
    """
    url = reverse("authenticator-list")
    saml_configuration["SP_PUBLIC_CERT"] = rsa_keypair_with_cert_1.certificate
    data = {
        "name": "SAML authenticator (should not get created)",
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "configuration": saml_configuration,
        "type": "ansible_base.authentication.authenticator_plugins.saml",
    }
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400
    assert any("The certificate and private key do not match" in err for err in response.data["SP_PRIVATE_KEY"])


@pytest.mark.django_db
def test_saml_metadata_on_ldap_authenticator(admin_api_client, ldap_authenticator):
    url = reverse('authenticator-metadata', kwargs={'pk': ldap_authenticator.id})
    response = admin_api_client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_saml_metadata_on_good_saml_authenticator(admin_api_client, saml_authenticator):
    url = reverse('authenticator-metadata', kwargs={'pk': saml_authenticator.id})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    headers = response.headers
    assert str(headers['content-type']) == 'text/xml'


@pytest.mark.django_db
def test_saml_metadata_on_bad_saml_authenticator(admin_api_client, saml_authenticator):
    saml_authenticator.configuration['CALLBACK_URL'] = ''
    saml_authenticator.save()
    url = reverse('authenticator-metadata', kwargs={'pk': saml_authenticator.id})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    headers = response.headers
    assert str(headers['content-type']) == 'text/plain'
    assert response.content.decode("utf-8") == 'Invalid dict settings: sp_acs_not_found'
