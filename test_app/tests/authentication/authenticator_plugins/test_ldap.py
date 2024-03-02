from collections import OrderedDict
from unittest import mock
from unittest.mock import MagicMock

import ldap
import pytest
from django.urls import reverse
from rest_framework.serializers import ValidationError

# from beartype import beartype
# from typing import no_type_check

from ansible_base.authentication.authenticator_plugins.ldap import AuthenticatorPlugin, LDAPSettings, validate_ldap_filter
from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.session import SessionAuthentication
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.AuthenticatorPlugin.authenticate")
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
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.AuthenticatorPlugin.authenticate", return_value=None)
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
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.AuthenticatorPlugin.authenticate", return_value=None)
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.config.LDAPSearch", side_effect=Exception("Something went wrong"))
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
        "type": "ansible_base.authentication.authenticator_plugins.ldap",
    }
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400
    assert "Something went wrong" in response.data["USER_SEARCH"][0]
    assert "Something went wrong" in response.data["GROUP_SEARCH"][0]


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@pytest.mark.parametrize(
    "setting_override, expected_errors",
    [
        ({"BIND_PASSWORD": False}, {"BIND_PASSWORD": "Not a valid string."}),
        ({"SERVER_URI": "foobar"}, {"SERVER_URI": 'Expected a list of items but got type "str".'}),
        (
            {"SERVER_URI": ["https://not.ldap.example.com"]},
            {"SERVER_URI": "https://not.ldap.example.com is invalid"},
        ),
        ({"-SERVER_URI": None}, {"SERVER_URI": "This field is required."}),
        ({"START_TLS": "foobar"}, {"START_TLS": "Must be a valid boolean."}),
        ({"USER_ATTR_MAP": {"email": False}}, {"USER_ATTR_MAP": {"email": "Must be a string"}}),
        ({"USER_ATTR_MAP": {"email": False, "monkey": 39}}, {"USER_ATTR_MAP": {"email": "Must be a string", "monkey": "Is not valid"}}),
        # TODO: Should this fail? We set configuration_valid=False, but don't set an error so the serializer accepts it.
        ({"-USER_ATTR_MAP": None}, None),
        ({"UNKNOWN_SETTING": "foobar"}, {"UNKNOWN_SETTING": "UNKNOWN_SETTING is not a supported configuration option."}),
        ({"-CONNECTION_OPTIONS": None}, None),
        ({"CONNECTION_OPTIONS": "pineapple does not belong on pizza"}, {"CONNECTION_OPTIONS": 'Expected a dictionary of items but got type "str".'}),
        ({"CONNECTION_OPTIONS": {"badoption": "yep"}}, {"CONNECTION_OPTIONS": {"badoption": "Not a valid connection option"}}),
        ({"-GROUP_TYPE": None}, {"GROUP_TYPE": "This field is required."}),
        ({"GROUP_TYPE": 29}, {"GROUP_TYPE": '"29" is not a valid choice.'}),
        ({"GROUP_TYPE": "invalid"}, {"GROUP_TYPE": '"invalid" is not a valid choice.'}),
        ({"GROUP_TYPE_PARAMS": "groupofnames"}, {"GROUP_TYPE_PARAMS": 'Expected a dictionary of items but got type "str".'}),
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
        ({"GROUP_SEARCH": "not a list"}, {"GROUP_SEARCH": 'Expected a list of items but got type "str".'}),
        ({"USER_SEARCH": "not a list"}, {"USER_SEARCH": 'Expected a list of items but got type "str".'}),
        ({"GROUP_SEARCH": ["only", "two"]}, {"GROUP_SEARCH": "Must be an array of 3 items: search DN, search scope and a filter"}),
        ({"USER_SEARCH": ["ou=users,dc=example,dc=org", "SCOPE_SUBTREE", "invalid"]}, None),
        ({"USER_SEARCH": ["invalid", "SCOPE_SUBTREE", "(cn=%(user)s)"]}, None),
        (
            {"USER_SEARCH": ["ou=users,dc=example,dc=org", "invalid", "(cn=%(user)s)"]},
            {"USER_SEARCH": {1: "Must be a string representing an LDAP scope object"}},
        ),
        ({"USER_SEARCH": ["ou=users,dc=example,dc=org", 1337, "(cn=%(user)s)"]}, {"USER_SEARCH": {1: "Must be a string representing an LDAP scope object"}}),
        (
            {"USER_SEARCH": ["ou=users,dc=example,dc=org", True, "(cn=%(user)s)"]},
            {"USER_SEARCH": {1: "Must be a string representing an LDAP scope object"}},
        ),
        ({"GROUP_SEARCH": ["ou=groups,dc=example,dc=org", "SCOPE_SUBTREE", "(&(|(objectClass=person))(uid=jdoe)(cn=%(user)s))"]}, None),
        ({"GROUP_SEARCH": ["ou=groups,dc=example,dc=org", "SCOPE_SUBTREE", 1337]}, {"GROUP_SEARCH": {2: "Must be a valid string"}}),
        ({"BIND_DN": ""}, None),
        ({"BIND_DN": False}, None),
        ({"USER_DN_TEMPLATE": ""}, None),
        ({"USER_DN_TEMPLATE": False}, {"USER_DN_TEMPLATE": "Not a valid string."}),
        ({"USER_DN_TEMPLATE": "cn=invalid,ou=users,dc=example,dc=org"}, {"USER_DN_TEMPLATE": 'DN must include "%(user)s"'}),
    ],
)
def test_ldap_create_authenticator_error_handling(
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
        "type": "ansible_base.authentication.authenticator_plugins.ldap",
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
                assert any(value in item for item in response.data[key])
            else:
                assert value in response.data[key]


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
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.LDAPBackend.authenticate", return_value=None)
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.logger")
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
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.LDAPBackend.authenticate", return_value=None)
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.logger")
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


# @no_type_check
@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.LDAPBackend.authenticate")
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.logger")
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
    assert response.data['results'][0]['name'] == ldap_authenticator.name


# @no_type_check
@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.LDAPBackend.authenticate")
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.logger")
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
    assert response.data['results'][0]['name'] == ldap_authenticator.name


@pytest.mark.django_db
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.LDAPBackend.authenticate")
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.logger")
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


@pytest.fixture
def ldap_settings(ldap_configuration):
    return LDAPSettings(defaults=ldap_configuration)


def test_ldap_validate_connection_options_newctx_comes_last(ldap_configuration):
    ldap_configuration["CONNECTION_OPTIONS"]["OPT_X_TLS_NEWCTX"] = 0
    ldap_configuration["CONNECTION_OPTIONS"]["OPT_X_TLS_PACKAGE"] = "GnuTLS"
    settings = LDAPSettings(defaults=ldap_configuration)
    assert settings.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] == 0
    assert isinstance(settings.CONNECTION_OPTIONS, OrderedDict)
    last_key = next(reversed(settings.CONNECTION_OPTIONS))
    assert last_key == ldap.OPT_X_TLS_NEWCTX


def test_ldap_validate_ldap_filter(ldap_configuration, ldap_settings):
    """
    Ensure we handle invalid subfilters correctly.

    validate_ldap_filter should return False if the overall filter is invalid.
    """
    invalid_filter = "(&(cn=%(user)s)(objectClass=posixAccount)(invalid))"
    with pytest.raises(ValidationError) as e:
        validate_ldap_filter(invalid_filter, True)
    assert e.value.args[0] == 'Invalid filter: (invalid)'


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.logger")
def test_AuthenticatorPlugin_authenticate_authenticator_disabled(logger, ldap_authenticator, ldap_settings):
    """
    Ensure we handle disabled authenticators correctly in AuthenticatorPlugin.authenticate.

    Normally we cannot hit this case (thus we cannot write a functional test for it), because
    we filter for enabled authenticators only. But perhaps in the future we will
    call this differently, so it's worth keeping the safeguard in place.

    This tests that safeguard.
    """
    ldap_authenticator.enabled = False
    ldap_authenticator.save()
    backend = AuthenticatorPlugin(database_instance=ldap_authenticator)
    request = MagicMock()
    assert backend.authenticate(request, username="foo", password="bar") is None
    logger.info.assert_called_with(f"LDAP authenticator {ldap_authenticator.name} is disabled, skipping")


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.logger")
def test_AuthenticatorPlugin_authenticate_no_authenticator(logger):
    """
    Test how AuthenticatorPlugin.authenticate handles no authenticator.
    """
    backend = AuthenticatorPlugin(database_instance=None)
    request = MagicMock()
    assert backend.authenticate(request, username="foo", password="bar") is None
    logger.error.assert_called_with("AuthenticatorPlugin was missing an authenticator")


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins.ldap.LDAPBackend.authenticate", return_value=None)
@pytest.mark.parametrize(
    "extra_settings, newctx_value",
    [
        ({}, None),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True}, "START_TLS": True}, 0),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True}, "START_TLS": False}, None),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": False}, "START_TLS": True}, 0),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": False}, "START_TLS": False}, None),
        ({"CONNECTION_OPTIONS": {}, "START_TLS": False}, None),
        ({"CONNECTION_OPTIONS": {}, "START_TLS": True}, None),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True, "OPT_X_TLS_NEWCTX": 1}, "START_TLS": True}, 0),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True, "OPT_X_TLS_NEWCTX": 1}, "START_TLS": False}, 1),
    ],
    ids=[
        "START_TLS not specified",
        "START_TLS enabled, OPT_X_TLS_REQUIRE_CERT enabled",
        "START_TLS disabled, OPT_X_TLS_REQUIRE_CERT enabled",
        "START_TLS enabled, OPT_X_TLS_REQUIRE_CERT disabled",
        "START_TLS disabled, OPT_X_TLS_REQUIRE_CERT disabled",
        "START_TLS disabled, no OPT_X_TLS_REQUIRE_CERT",
        "START_TLS enabled, no OPT_X_TLS_REQUIRE_CERT",
        "Existing OPT_X_TLS_NEWCTX gets forced to 0 (START_TLS enabled)",
        "Existing OPT_X_TLS_NEWCTX gets preserved (START_TLS disabled)",
    ],
)
def test_AuthenticatorPlugin_authenticate_start_tls(authenticate, ldap_authenticator, extra_settings, newctx_value, shut_up_logging):
    """
    Ensure we force OPT_X_TLS_NEWCTX to 0 (only) when START_TLS is enabled.

    Conditions:
    - START_TLS enabled in settings
    - OPT_X_TLS_REQUIRE_CERT enabled in settings.CONNECTION_OPTIONS
    """
    ldap_authenticator.configuration.update(extra_settings)
    ldap_authenticator.save()
    # settings = LDAPSettings(defaults=ldap_authenticator.configuration)
    backend = AuthenticatorPlugin(database_instance=ldap_authenticator)
    request = MagicMock()
    assert backend.authenticate(request, username="foo", password="bar") is None
    if newctx_value is not None:
        assert backend.settings.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] == newctx_value
    else:
        assert ldap.OPT_X_TLS_NEWCTX not in backend.settings.CONNECTION_OPTIONS
