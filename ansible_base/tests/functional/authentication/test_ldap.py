from unittest import mock
from unittest.mock import MagicMock

import pytest
from django.urls import reverse

from ansible_base.authentication.session import SessionAuthentication
from ansible_base.models import Authenticator
from ansible_base.utils.encryption import ENCRYPTED_STRING

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.AuthenticatorPlugin.authenticate")
def test_ldap_auth_successful(authenticate, unauthenticated_api_client, ldap_authenticator, user):
    """
    Test that a successful LDAP authentication returns a 200 on the /me endpoint.

    Here we mock the LDAP authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.AuthenticatorPlugin.authenticate", return_value=None)
def test_ldap_auth_failed(authenticate, unauthenticated_api_client, ldap_authenticator):
    """
    Test that a failed LDAP authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.AuthenticatorPlugin.authenticate", return_value=None)
@mock.patch("ansible_base.authenticator_plugins.ldap.config.LDAPSearch", side_effect=Exception("Something went wrong"))
def test_ldap_search_exception(
    LDAPSearch,
    authenticate,
    admin_api_client,
    ldap_configuration,
    user,
):
    """
    Test handling if config.LDAPSearch raises an exception.
    """
    url = reverse("authenticator-list")
    data = {
        "name": "LDAP authenticator (should not get created)",
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "configuration": ldap_configuration,
        "type": "ansible_base.authenticator_plugins.ldap",
    }
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400
    assert "Something went wrong" in response.data["configuration"]["USER_SEARCH"]
    assert "Something went wrong" in response.data["configuration"]["GROUP_SEARCH"]


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.AuthenticatorPlugin.authenticate")
@pytest.mark.parametrize(
    "setting_override, expected_errors",
    [
        ({"BIND_PASSWORD": False}, {"BIND_PASSWORD": "Must be a valid string"}),
        ({"SERVER_URI": "foobar"}, {"SERVER_URI": "Must be a list of urls"}),
        (
            {"SERVER_URI": ["https://not.ldap.example.com"]},
            {"SERVER_URI": "SERVER_URI must contain only valid urls with schemes ldap, ldaps, the following are invalid: https://not.ldap.example.com"},
        ),
        ({"-SERVER_URI": None}, {"SERVER_URI": "Must be a list of valid LDAP URLs"}),
        ({"START_TLS": "foobar"}, {"START_TLS": "Must be a boolean value"}),
        ({"USER_ATTR_MAP": {"email": False}}, {"USER_ATTR_MAP.email": "Must be a string"}),
        ({"USER_ATTR_MAP": {"email": False, "monkey": 39}}, {"USER_ATTR_MAP.email": "Must be a string", "USER_ATTR_MAP.monkey": "Is not valid"}),
        # TODO: Should this fail? We set configuration_valid=False, but don't set an error so the serializer accepts it.
        ({"-USER_ATTR_MAP": None}, None),
        ({"UNKNOWN_SETTING": "foobar"}, {"UNKNOWN_SETTING": "Is not a valid setting for an LDAP authenticator"}),
        ({"-CONNECTION_OPTIONS": None}, None),
        ({"CONNECTION_OPTIONS": "pineapple does not belong on pizza"}, {"CONNECTION_OPTIONS": "Must be a dict of options"}),
        ({"CONNECTION_OPTIONS": {"badoption": "yep"}}, {"CONNECTION_OPTIONS.badoption": "Not a valid connection option"}),
        ({"-GROUP_TYPE": None}, {"GROUP_TYPE": "Must be present"}),
        ({"GROUP_TYPE": 29}, {"GROUP_TYPE": "Must be string"}),
        ({"GROUP_TYPE": "invalid"}, {"GROUP_TYPE": "Specified group type is invalid"}),
        ({"GROUP_TYPE_PARAMS": "groupofnames"}, {"GROUP_TYPE_PARAMS": "Must be a dict object"}),
        ({"GROUP_TYPE_PARAMS": {"badparam": "yep"}}, {"GROUP_TYPE_PARAMS.badparam": "Invalid option for specified GROUP_TYPE"}),
        ({"GROUP_TYPE_PARAMS": {"member_attr": "yep"}}, {"GROUP_TYPE_PARAMS.name_attr": "Missing required field for GROUP_TYPE"}),
        ({"GROUP_TYPE_PARAMS": {"name_attr": "yep"}}, {"GROUP_TYPE_PARAMS.member_attr": "Missing required field for GROUP_TYPE"}),
        ({"GROUP_TYPE_PARAMS": {"member_attr": "yep", "name_attr": "yep"}}, None),
        (
            {"GROUP_TYPE_PARAMS": {"member_attr": "yep", "name_attr": "yep", "badparam": "yep"}},
            {"GROUP_TYPE_PARAMS.badparam": "Invalid option for specified GROUP_TYPE"},
        ),
        (
            {"GROUP_TYPE_PARAMS": {"member_attr": "yep", "name_attr": "yep", "badparam": "yep", "badparam2": "yep"}},
            {"GROUP_TYPE_PARAMS.badparam": "Invalid option for specified GROUP_TYPE", "GROUP_TYPE_PARAMS.badparam2": "Invalid option for specified GROUP_TYPE"},
        ),
        ({"USER_SEARCH": None}, None),
        ({"GROUP_SEARCH": None}, None),
        ({"GROUP_SEARCH": None, "USER_SEARCH": None}, None),
        ({"GROUP_SEARCH": [], "USER_SEARCH": []}, None),
        ({"GROUP_SEARCH": "not a list"}, {"GROUP_SEARCH": "Must be an array of 3 items:"}),
        ({"USER_SEARCH": "not a list"}, {"USER_SEARCH": "Must be an array of 3 items:"}),
        ({"GROUP_SEARCH": ["only", "two"]}, {"GROUP_SEARCH": "Must be an array of 3 items:"}),
        ({"USER_SEARCH": ["ou=users,dc=example,dc=org", "SCOPE_SUBTREE", "invalid"]}, None),
        ({"USER_SEARCH": ["invalid", "SCOPE_SUBTREE", "(cn=%(user)s)"]}, None),
        ({"USER_SEARCH": ["ou=users,dc=example,dc=org", "invalid", "(cn=%(user)s)"]}, {"USER_SEARCH.1": "Must be a string representing an LDAP scope object"}),
        ({"USER_SEARCH": ["ou=users,dc=example,dc=org", 1337, "(cn=%(user)s)"]}, {"USER_SEARCH.1": "Must be a string representing an LDAP scope object"}),
        (
            {"USER_SEARCH": ["ou=users,dc=example,dc=org", True, "(cn=%(user)s)"]},
            {"USER_SEARCH.1": "Must be a string representing an LDAP scope object"},
        ),
        ({"GROUP_SEARCH": ["ou=groups,dc=example,dc=org", "SCOPE_SUBTREE", "(&(|(objectClass=person))(uid=jdoe)(cn=%(user)s))"]}, None),
        ({"GROUP_SEARCH": ["ou=groups,dc=example,dc=org", "SCOPE_SUBTREE", 1337]}, {"GROUP_SEARCH.2": "Must be a valid string"}),
        ({"BIND_DN": ""}, None),
        ({"BIND_DN": False}, None),
        ({"USER_DN_TEMPLATE": ""}, None),
        ({"USER_DN_TEMPLATE": False}, {"USER_DN_TEMPLATE": "Must be a valid string"}),
        ({"USER_DN_TEMPLATE": "cn=invalid,ou=users,dc=example,dc=org"}, {"USER_DN_TEMPLATE": "DN must include \"%(user)s\""}),
    ],
)
def test_ldap_create_authenticator_error_handling(
    authenticate,
    admin_api_client,
    ldap_configuration,
    user,
    setting_override,
    expected_errors,
    shut_up_logging,
):
    """
    Tests various error conditions that arise when validating the configuration of an LDAP authenticator.
    """
    for key, value in setting_override.items():
        if key.startswith("-"):
            del ldap_configuration[key[1:]]
        else:
            ldap_configuration[key] = value

    url = reverse("authenticator-list")
    data = {
        "name": "LDAP authenticator (should not get created)",
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "configuration": ldap_configuration,
        "type": "ansible_base.authenticator_plugins.ldap",
    }
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400 if expected_errors else 201
    if expected_errors:
        for key, value in expected_errors.items():
            assert key in response.data["configuration"]
            assert value in response.data["configuration"][key]


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
def test_ldap_backend_authenticate_encrypted_fields_update(admin_api_client, ldap_authenticator, shut_up_logging):
    url = reverse("authenticator-detail", kwargs={"pk": ldap_authenticator.pk})
    # BIND_PASSWORD is encrypted
    config = ldap_authenticator.configuration
    config["BIND_PASSWORD"] = 'foo'
    response = admin_api_client.patch(url, data={"configuration": config}, format="json")
    assert response.status_code == 200
    assert response.data["configuration"]["BIND_PASSWORD"] == ENCRYPTED_STRING
    authenticator = Authenticator.objects.get(pk=ldap_authenticator.pk)
    # We automatically decrypt the encrypted fields in Authenticator#from_db
    assert authenticator.configuration["BIND_PASSWORD"] == "foo"

    # And updating it to ENCRYPTED_STRING should not change the value
    config["BIND_PASSWORD"] = ENCRYPTED_STRING
    response = admin_api_client.patch(url, data={"configuration": config}, format="json")
    assert response.status_code == 200
    assert response.data["configuration"]["BIND_PASSWORD"] == ENCRYPTED_STRING
    authenticator = Authenticator.objects.get(pk=ldap_authenticator.pk)
    assert authenticator.configuration["BIND_PASSWORD"] == "foo"


@pytest.mark.xfail(reason="https://issues.redhat.com/browse/AAP-17453")
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
def test_ldap_backend_validate_configuration_warn_specific_fields(
    shut_up_logging,  # TODO: Remove with xfail
    admin_api_client,
    ldap_authenticator,
):
    config = ldap_authenticator.configuration
    config["DENY_GROUP"] = "cn=deniedgroup,ou=groups,dc=example,dc=org"

    url = reverse("authenticator-detail", kwargs={"pk": ldap_authenticator.pk})
    response = admin_api_client.patch(url, data={"configuration": config}, format="json")
    assert response.status_code == 200
    assert "better to use the authenticator field" in response.data["warnings"]["DENY_GROUP"]


@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
def test_ldap_backend_authenticate_configuration_invalid(
    logger,
    unauthenticated_api_client,
    ldap_authenticator,
    shut_up_logging,
):
    """
    Ensure we log properly when the LDAP configuration is invalid.
    """
    del ldap_authenticator.configuration["USER_ATTR_MAP"]
    ldap_authenticator.save()
    unauthenticated_api_client.login(username="foo", password="bar")
    url = reverse(authenticated_test_page)
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401
    logger.error.assert_any_call(f"LDAP authenticator {ldap_authenticator.name} can not be used due to configuration errors.")


@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.LDAPBackend.authenticate", return_value=None)
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
@pytest.mark.parametrize(
    "extra_settings,expected_message",
    [
        ({"REQUIRE_GROUP": "cn=requiredgroup,ou=groups,dc=example,dc=org"}, "Hint: is user missing required group?"),
        ({"DENY_GROUP": "cn=deniedgroup,ou=groups,dc=example,dc=org"}, "Hint: is user in deny group?"),
        (
            {"REQUIRE_GROUP": "cn=requiredgroup,ou=groups,dc=example,dc=org", "DENY_GROUP": "cn=deniedgroup,ou=groups,dc=example,dc=org"},
            "Hint: is user missing required group or in deny group?",
        ),
        ({}, None),  # no extra settings, just show the "could not be authenticated" message
    ],
)
def test_ldap_backend_authenticate_invalid_user(
    logger,
    authenticate,
    unauthenticated_api_client,
    ldap_authenticator,
    shut_up_logging,
    extra_settings,
    expected_message,
):
    """
    Test normal login flow when authenticate() returns no user.
    """
    ldap_authenticator.configuration.update(extra_settings)
    ldap_authenticator.save()
    unauthenticated_api_client.login(username="foo", password="bar")
    url = reverse(authenticated_test_page)
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401
    logger.info.assert_any_call(f"User foo could not be authenticated by LDAP {ldap_authenticator.name}")
    if expected_message:
        logger.info.assert_any_call(expected_message)


@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.LDAPBackend.authenticate", return_value=None)
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
@pytest.mark.parametrize(
    "username,password",
    [
        ("user", "invalidpassword"),
        ("invaliduser", "password"),
        ("", "invalidpassword"),
        ("invaliduser", ""),
        ("", ""),
    ],
)
def test_ldap_backend_authenticate_empty_username_password(
    logger,
    authenticate,
    unauthenticated_api_client,
    ldap_authenticator,
    shut_up_logging,
    username,
    password,
):
    """
    Test login flow when authenticate() gets a blank username/password.
    """
    unauthenticated_api_client.login(username=username, password=password)
    url = reverse(authenticated_test_page)
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401


@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.LDAPBackend.authenticate")
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
def test_ldap_backend_authenticate_valid_user(
    logger,
    authenticate,
    unauthenticated_api_client,
    ldap_authenticator,
    shut_up_logging,
    user,
):
    """
    Test normal login flow. Force authenticate() to return a user.
    """
    user.ldap_user = MagicMock()
    authenticate.return_value = user
    client = unauthenticated_api_client
    client.login(username=user.username, password="bar")
    url = reverse(authenticated_test_page)
    response = client.get(url)
    logger.debug.assert_any_call(f"Forcing LDAP connection to close for {ldap_authenticator.name}")
    logger.info.assert_any_call(f"User {user.username} authenticated by LDAP {ldap_authenticator.name}")
    assert user.ldap_user._connection.unbind_s.call_count == 1
    assert user.ldap_user._connection_bound is False
    assert response.status_code == 200
    assert response.data[0]['name'] == ldap_authenticator.name


@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.LDAPBackend.authenticate")
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
def test_ldap_backend_authenticate_unbind_exception(
    logger,
    authenticate,
    unauthenticated_api_client,
    ldap_authenticator,
    shut_up_logging,
    user,
):
    """
    Test normal login flow. Force authenticate() to return a user.
    But an exception is thrown during unbind.
    """
    user.ldap_user = MagicMock()
    user.ldap_user._connection.unbind_s.side_effect = Exception("Something went wrong")
    authenticate.return_value = user
    client = unauthenticated_api_client
    client.login(username=user.username, password="bar")
    url = reverse(authenticated_test_page)
    response = client.get(url)
    logger.exception.assert_any_call(f"Got unexpected LDAP exception when forcing LDAP disconnect for user {user.username}, login will still proceed")
    assert response.status_code == 200
    assert response.data[0]['name'] == ldap_authenticator.name


@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.ldap.LDAPBackend.authenticate")
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
def test_ldap_backend_authenticate_exception(
    logger,
    authenticate,
    unauthenticated_api_client,
    ldap_authenticator,
    shut_up_logging,
):
    """
    Normal login flow, but encounters an exception when authenticating to LDAP.
    """
    authenticate.side_effect = Exception("Something went wrong")
    client = unauthenticated_api_client
    client.login(username="someuser", password="bar")
    url = reverse(authenticated_test_page)
    response = client.get(url)
    logger.exception.assert_called_with(f"Encountered an error authenticating to LDAP {ldap_authenticator.name}")
    assert response.status_code == 401
