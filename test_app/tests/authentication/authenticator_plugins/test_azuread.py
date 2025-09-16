from unittest import mock

import pytest
from django.test import override_settings

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.session import SessionAuthentication
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.utils.response import get_fully_qualified_url, get_relative_url

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.azuread.AuthenticatorPlugin.authenticate")
def test_azuread_auth_successful(authenticate, unauthenticated_api_client, azuread_authenticator, user):
    """
    Test that a successful AzureADauthentication returns a 200 on the /me endpoint.

    Here we mock the AzureAD authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "key, secret, expected_status_code, expected_error",
    [
        (None, None, 400, {'KEY': ['This field may not be null.']}),
        ('', None, 400, {'KEY': ['This field may not be blank.']}),
        ('testaz', '', 400, {'SECRET': ['This field may not be blank.']}),
        ('testaz', None, 201, {}),
        ('testaz', "testaz_secret", 201, {}),
    ],
)
def test_azuread_callback_url_validation(
    admin_api_client,
    key,
    secret,
    expected_status_code,
    expected_error,
):
    config = {"KEY": key, "SECRET": secret}

    data = {
        "name": "AZUREAD TEST",
        "enabled": True,
        "create_objects": True,
        "remove_users": True,
        "configuration": config,
        "type": "ansible_base.authentication.authenticator_plugins.azuread",
    }

    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == expected_status_code
    if expected_error:
        assert response.json() == expected_error
    else:
        slug = response.data["slug"]
        with override_settings(FRONT_END_URL='http://testserver/'):
            expected_path = get_fully_qualified_url('social:complete', kwargs={'backend': slug})
            assert response.json()['configuration']['CALLBACK_URL'] == expected_path


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.azuread.AuthenticatorPlugin.authenticate", return_value=None)
def test_azuread_auth_failed(authenticate, unauthenticated_api_client, azuread_authenticator):
    """
    Test that a failed AzureAD authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


def test_groups_setting_and_user_groups(keycloak_authenticator):
    custom_groups_claim = "some_groups"

    class MockedDb:
        def __init__(self, group_claim):
            self.slug = "fake"
            self.configuration = {"GROUPS_CLAIM": group_claim}

    class MockBackend(SocialAuthMixin):
        database_instance = MockedDb(custom_groups_claim)

        def __init__(self):
            pass

    backend = MockBackend()

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb(custom_groups_claim)

    # assert that groups claim setting is there and AD has the expected groups claim
    assert ad.strategy.get_setting('GROUPS_CLAIM', backend) == custom_groups_claim
    assert ad.groups_claim == custom_groups_claim

    # assert that AD returns expected user groups
    assert ad.get_user_groups() == []
    assert ad.get_user_groups(["a", "b"]) == ["a", "b"]


def test_get_user_details_basic_functionality():
    """Test basic get_user_details functionality without USERNAME_FIELD"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb(None)

    username = 'bob'
    email = 'bob@example.com'

    response = {
        "name": username,
        "given_name": "Joe",
        "family_name": "LastName",
        "email": email,
        "upn": "upn123",
    }

    result = ad.get_user_details(response)
    assert result['username'] == username
    assert result['first_name'] == "Joe"
    assert result['last_name'] == "LastName"
    assert result['email'] == email


@pytest.mark.parametrize(
    "username_field, expected_username",
    [
        ("email", "bob@example.com"),
        ("upn", "bob@company.com"),
        ("given_name", "Joe"),
        ("family_name", "LastName"),
        ("name", "bob"),
    ],
)
def test_get_user_details_with_username_field(username_field, expected_username):
    """Test get_user_details with different USERNAME_FIELD configurations"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb(username_field)

    response = {
        "name": "bob",
        "given_name": "Joe",
        "family_name": "LastName",
        "email": "bob@example.com",
        "upn": "bob@company.com",
    }

    result = ad.get_user_details(response)
    assert result['username'] == expected_username


@pytest.mark.parametrize(
    "missing_field, fallback_username, response_data",
    [
        (
            "nonexistent_field",
            "bob",
            {
                "name": "bob",
                "given_name": "Joe",
                "family_name": "LastName",
                "email": "bob@example.com",
                "upn": "upn123",
            },
        ),
        (
            "missing_email",
            "alice",
            {
                "name": "alice",
                "given_name": "Alice",
                "family_name": "Smith",
                "upn": "alice@company.com",
            },
        ),
        (
            "invalid_field",
            "charlie",
            {
                "name": "charlie",
                "email": "charlie@test.com",
                "custom_field": "custom_value",
            },
        ),
    ],
)
def test_get_user_details_username_field_not_found(caplog, missing_field, fallback_username, response_data):
    """Test get_user_details when USERNAME_FIELD is not found in response"""
    import logging

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb(missing_field)

    with caplog.at_level(logging.WARNING):
        result = ad.get_user_details(response_data)

    # Should fall back to default username
    assert result['username'] == fallback_username

    # Should log warnings - check for key parts of the messages
    assert f"Username field '{missing_field}' not found" in caplog.text
    assert f"using default username of {fallback_username}" in caplog.text
    assert "Valid keys are:" in caplog.text


def test_get_user_details_with_tokens():
    """Test get_user_details with access_token and id_token processing"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb('preferred_username')

    # Mock the user_data method to return additional data from token
    with mock.patch.object(ad, 'user_data') as mock_user_data:
        mock_user_data.return_value = {
            "preferred_username": "bob_preferred",
            "roles": ["admin", "user"],
            "sub": "12345",
        }

        response = {
            "name": "bob",
            "email": "bob@example.com",
            "access_token": "fake_access_token",
            "id_token": "fake_id_token",
        }

        result = ad.get_user_details(response)

        # Should use preferred_username from token data
        assert result['username'] == "bob_preferred"

        # Should have called user_data with access_token
        mock_user_data.assert_called_once_with("fake_access_token", response=response)


def test_get_user_details_token_data_merging():
    """Test that data from tokens is properly merged with response data"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb('custom_field')

    # Mock user_data to return additional fields including the custom field
    with mock.patch.object(ad, 'user_data') as mock_user_data:
        mock_user_data.return_value = {
            "custom_field": "custom_username",
            "additional_info": "from_token",
            "email": "token_email@example.com",  # This should override response email
        }

        response = {
            "name": "bob",
            "email": "response_email@example.com",
            "access_token": "fake_access_token",
            "id_token": "fake_id_token",
        }

        result = ad.get_user_details(response)

        # Should use custom_field from token data
        assert result['username'] == "custom_username"

        # The super().get_user_details() result takes precedence over token data for standard fields
        # So email should come from response, not token
        assert result['email'] == "response_email@example.com"


def test_get_user_details_without_tokens():
    """Test get_user_details when no access_token or id_token is present"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb('email')

    response = {
        "name": "bob",
        "email": "bob@example.com",
        "given_name": "Bob",
        "family_name": "Smith",
    }

    result = ad.get_user_details(response)

    # Should still work without tokens
    assert result['username'] == "bob@example.com"
    assert result['first_name'] == "Bob"
    assert result['last_name'] == "Smith"


@pytest.mark.parametrize(
    "token_scenario, response_data, should_call_user_data",
    [
        (
            "access_token_only",
            {
                "name": "bob",
                "email": "bob@example.com",
                "access_token": "fake_access_token",
            },
            False,  # Should not call user_data without both tokens
        ),
        (
            "id_token_only",
            {
                "name": "alice",
                "email": "alice@example.com",
                "id_token": "fake_id_token",
            },
            False,  # Should not call user_data without both tokens
        ),
        (
            "both_tokens",
            {
                "name": "charlie",
                "email": "charlie@example.com",
                "access_token": "fake_access_token",
                "id_token": "fake_id_token",
            },
            True,  # Should call user_data with both tokens
        ),
        (
            "no_tokens",
            {
                "name": "diana",
                "email": "diana@example.com",
            },
            False,  # Should not call user_data without tokens
        ),
    ],
)
def test_get_user_details_token_scenarios(token_scenario, response_data, should_call_user_data):
    """Test get_user_details with different token combinations"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb(None)

    with mock.patch.object(ad, 'user_data') as mock_user_data:
        mock_user_data.return_value = {"extra_field": "extra_value"}

        result = ad.get_user_details(response_data)

        # Should use name as username since no USERNAME_FIELD is configured
        expected_username = response_data["name"]
        assert result['username'] == expected_username

        # Check if user_data was called based on expectation
        if should_call_user_data:
            mock_user_data.assert_called_once_with(response_data['access_token'], response=response_data)
        else:
            mock_user_data.assert_not_called()


def test_get_user_details_username_field_priority():
    """Test that USERNAME_FIELD searches in the right order: response -> token -> super()"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb('test_field')

    # Mock user_data to return token data
    with mock.patch.object(ad, 'user_data') as mock_user_data:
        mock_user_data.return_value = {
            "test_field": "from_token",
            "other_field": "token_value",
        }

        # Response has the field - should use response value
        response = {
            "name": "bob",
            "test_field": "from_response",
            "access_token": "fake_access_token",
            "id_token": "fake_id_token",
        }

        result = ad.get_user_details(response)
        # Token data should override response data, so should get token value
        assert result['username'] == "from_token"


@pytest.mark.parametrize(
    "username_field, token_data, response_data, expected_username, expected_email",
    [
        (
            "token_only_field",
            {
                "token_only_field": "from_token_only",
                "name": "token_name",  # This will be overridden by super()
                "token_extra": "extra_data",
            },
            {
                "name": "response_name",
                "email": "response_email@example.com",
                "access_token": "fake_access_token",
                "id_token": "fake_id_token",
            },
            "from_token_only",  # USERNAME_FIELD should come from token
            "response_email@example.com",  # Standard fields come from super()
        ),
        (
            "email",
            {
                "preferred_username": "token_user",
                "email": "token_email@example.com",  # This will be overridden by super()
            },
            {
                "name": "response_user",
                "email": "response_email@example.com",
                "access_token": "fake_access_token",
                "id_token": "fake_id_token",
            },
            "response_email@example.com",  # USERNAME_FIELD comes from merged data (super() wins)
            "response_email@example.com",
        ),
        (
            "preferred_username",
            {
                "preferred_username": "preferred_user",
                "sub": "12345",
            },
            {
                "name": "basic_user",
                "email": "basic@example.com",
                "access_token": "fake_access_token",
                "id_token": "fake_id_token",
            },
            "preferred_user",  # USERNAME_FIELD from token data
            "basic@example.com",
        ),
    ],
)
def test_get_user_details_data_merging_behavior(username_field, token_data, response_data, expected_username, expected_email):
    """Test the specific behavior of how data gets merged between response, token, and super()"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb(username_field)

    # Mock user_data to return token data that has both overlapping and unique fields
    with mock.patch.object(ad, 'user_data') as mock_user_data:
        mock_user_data.return_value = token_data

        result = ad.get_user_details(response_data)

        # USERNAME_FIELD should come from the expected source
        assert result['username'] == expected_username

        # Standard fields should come from super().get_user_details() which processes the response
        assert result['email'] == expected_email


@pytest.mark.parametrize(
    "username_field, original_response, expected_username",
    [
        (
            "email",
            {
                "name": "bob",
                "email": "bob@example.com",
                "given_name": "Bob",
            },
            "bob@example.com",
        ),
        (
            "name",
            {
                "name": "alice",
                "email": "alice@test.com",
                "upn": "alice@company.com",
            },
            "alice",
        ),
        (
            None,  # No USERNAME_FIELD configured
            {
                "name": "charlie",
                "email": "charlie@example.com",
                "custom_field": "custom_value",
            },
            "charlie",  # Should use default username from super()
        ),
    ],
)
def test_get_user_details_data_immutability(username_field, original_response, expected_username):
    """Test that original response data is not modified"""

    class MockedDb:
        def __init__(self, username_field):
            self.slug = "fake"
            self.configuration = {"USERNAME_FIELD": username_field}

    ad = get_authenticator_plugin("ansible_base.authentication.authenticator_plugins.azuread")
    ad.database_instance = MockedDb(username_field)

    # Make a copy to compare
    response_copy = original_response.copy()

    result = ad.get_user_details(original_response)

    # Original response should not be modified
    assert original_response == response_copy

    # But result should have processed data
    assert result['username'] == expected_username
