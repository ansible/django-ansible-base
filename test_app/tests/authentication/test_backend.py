from random import shuffle
from types import SimpleNamespace
from unittest import mock

import pytest

import ansible_base.authentication.backend as backend
from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.social_auth import SOCIAL_AUTH_PIPELINE_FAILED_STATUS


@pytest.mark.django_db
def test_authenticator_backends_import_error(ldap_authenticator):
    # Load one item
    assert len(backend.get_authentication_backends("fake date")) == 1

    # Change the get_authenticator_plugin to fail, this will cause the backend to not be able to load
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        # Force the cache to get evicted by updating an authenticator.
        assert len(backend.get_authentication_backends("fake date2")) == 0


@pytest.mark.django_db
def test_authenticator_backends_cache(ldap_authenticator):
    last_modified = Authenticator.objects.values("modified").order_by("-modified").first()["modified"]

    # Load one item
    assert len(backend.get_authentication_backends(last_modified)) == 1

    # verify that the cache is evicted when an authenticator is updated.
    ldap_authenticator.name = "new_name"
    ldap_authenticator.save()

    last_modified = Authenticator.objects.values("modified").order_by("-modified").first()["modified"]
    authenticator = backend.get_authentication_backends(last_modified)[ldap_authenticator.pk]
    assert authenticator.database_instance.name == "new_name"

    # verify that the cache is not updated if the last_modified date is the same
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=OSError("Test Exception")):
        # If the function reruns, get_authenticator_plugin will throw an exception here
        authenticator = backend.get_authentication_backends(last_modified)[ldap_authenticator.pk]
        assert authenticator.database_instance.name == "new_name"


def shuffle_backends(backends):
    authenticator_ids = list(backends.keys())
    shuffle(authenticator_ids)

    for index, authenticator_id in enumerate(authenticator_ids):
        authenticator = Authenticator.objects.get(id=authenticator_id)
        authenticator.order = index
        authenticator.save()

    return authenticator_ids


@pytest.mark.django_db
def test_authenticator_order(
    github_authenticator,
    github_organization_authenticator,
    github_team_authenticator,
    github_enterprise_authenticator,
    github_enterprise_organization_authenticator,
    github_enterprise_team_authenticator,
    oidc_authenticator,
    ldap_authenticator,
    tacacs_authenticator,
    saml_authenticator,
    keycloak_authenticator,
    local_authenticator_map,
):
    # Get the authenticators from the backend (to filter out enabled or anything else its doing)
    authenticators = backend.get_authentication_backends(None)

    # Randomize the authenticators list
    ids_by_new_order = shuffle_backends(authenticators)

    # Get the backends form the code (which should respect order)
    # Note: that we need to specify a different value to not get a cached result
    ordered_authenticator_backends = backend.get_authentication_backends(1)

    # Convert the results to a list
    ordered_authenticator_id_list = []
    for authenticator_id, _authenticator_plugin in ordered_authenticator_backends.items():
        ordered_authenticator_id_list.append(authenticator_id)

    assert ordered_authenticator_id_list == ids_by_new_order


@pytest.mark.django_db
def test_authenticator_order_cached(
    github_authenticator,
    github_organization_authenticator,
    github_team_authenticator,
    github_enterprise_authenticator,
    github_enterprise_organization_authenticator,
    github_enterprise_team_authenticator,
    oidc_authenticator,
    ldap_authenticator,
    tacacs_authenticator,
    saml_authenticator,
    keycloak_authenticator,
    local_authenticator_map,
):
    # Get the authenticators from the backend (to filter out enabled or anything else its doing)
    backends = backend.get_authentication_backends(None)

    # Randomize the order of the authenticators
    shuffle_backends(backends)

    # test the cache
    cached_authenticators = backend.get_authentication_backends(None)
    assert cached_authenticators == backends

    # Bust the cache
    cached_authenticators = backend.get_authentication_backends(1)
    assert cached_authenticators != backends


@pytest.mark.parametrize(
    "github_auth_retval, is_active, expected",
    [
        ("random_user", None, "random_user"),
        ("random_user", False, None),
        ("random_user", True, "random_user"),
        (None, None, "random_user_1"),
        (None, False, "random_user_1"),
        (None, True, "random_user_1"),
        (SOCIAL_AUTH_PIPELINE_FAILED_STATUS, None, "random_user_1"),
        (SOCIAL_AUTH_PIPELINE_FAILED_STATUS, False, "random_user_1"),
        (SOCIAL_AUTH_PIPELINE_FAILED_STATUS, True, "random_user_1"),
    ],
)
def test_authenticate(request, local_authenticator, github_enterprise_authenticator, random_user, random_user_1, github_auth_retval, is_active, expected):
    with mock.patch(
        "ansible_base.authentication.backend.get_authentication_backends",
        return_value={github_enterprise_authenticator.id: github_enterprise_authenticator, local_authenticator.id: local_authenticator},
    ):
        # Set is_active flag for 1st authenticator's user
        if is_active is not None:
            setattr(random_user, "is_active", is_active)

        # Set response for 1st authenticator
        if github_auth_retval == "random_user":
            github_auth_retval = request.getfixturevalue(github_auth_retval)
        github_enterprise_authenticator.authenticate = mock.MagicMock(return_value=github_auth_retval)

        # If GitHub authenticator fails, next one always fits
        local_authenticator.authenticate = mock.MagicMock(return_value=random_user_1)

        auth_return = backend.AnsibleBaseAuth().authenticate(None)

        if expected is not None:
            expected = request.getfixturevalue(expected)

        assert auth_return == expected


@pytest.mark.django_db
def test_authentication_exception(expected_log):
    class MockAuthenticator:
        database_instance = SimpleNamespace(name='testing')

        def authenticate(*args, **kwars):
            raise Exception('eeekkkk')

    # Patch the backends to have our Mock authenticator in it
    with mock.patch(
        "ansible_base.authentication.backend.get_authentication_backends",
        return_value={1: MockAuthenticator()},
    ):
        # Expect the log we emit
        with expected_log('ansible_base.authentication.backend.logger', "exception", "Exception raised while trying to authenticate with"):
            backend.AnsibleBaseAuth().authenticate(None)


@pytest.mark.django_db
def test_last_login_from_with_attribute(local_authenticator, random_user, expected_log):
    """Test that last_login_from is set when user has the attribute."""
    # Add last_login_from attribute to user
    random_user.last_login_from = None

    # Create a mock authenticator plugin object with proper structure
    mock_authenticator_plugin = mock.MagicMock()
    mock_authenticator_plugin.authenticate.return_value = random_user
    mock_authenticator_plugin.database_instance = local_authenticator

    # Mock the save method to track calls
    with mock.patch.object(random_user, 'save') as mock_save:
        with mock.patch(
            "ansible_base.authentication.backend.get_authentication_backends",
            return_value={local_authenticator.id: mock_authenticator_plugin},
        ):
            # Expected log message when user logs in
            with expected_log(
                'ansible_base.authentication.backend.logger',
                "info",
                f'User {random_user.username} logged in from authenticator with ID "{local_authenticator.id}"',
            ):
                auth_return = backend.AnsibleBaseAuth().authenticate(None)

            # Verify the user is returned
            assert auth_return == random_user

            # Verify last_login_from was set to the authenticator database instance
            assert random_user.last_login_from == local_authenticator

            # Verify save was called with the correct update_fields
            mock_save.assert_called_once_with(update_fields=['last_login_from'])


@pytest.mark.django_db
def test_last_login_from_without_attribute(local_authenticator, random_user, expected_log):
    """Test that authentication works normally when user doesn't have last_login_from attribute."""
    # Ensure user doesn't have last_login_from attribute
    if hasattr(random_user, 'last_login_from'):
        delattr(random_user, 'last_login_from')

    # Create a mock authenticator plugin object with proper structure
    mock_authenticator_plugin = mock.MagicMock()
    mock_authenticator_plugin.authenticate.return_value = random_user
    mock_authenticator_plugin.database_instance = local_authenticator

    # Mock the save method to track calls
    with mock.patch.object(random_user, 'save') as mock_save:
        with mock.patch(
            "ansible_base.authentication.backend.get_authentication_backends",
            return_value={local_authenticator.id: mock_authenticator_plugin},
        ):
            with expected_log(
                'ansible_base.authentication.backend.logger',
                "info",
                f'User {random_user.username} logged in from authenticator with ID "{local_authenticator.id}"',
            ):
                auth_return = backend.AnsibleBaseAuth().authenticate(None)

            # Verify the user is returned
            assert auth_return == random_user

            # Verify save was never called since user doesn't have last_login_from
            mock_save.assert_not_called()


@pytest.mark.django_db
def test_last_login_from_multiple_authenticators(local_authenticator, github_enterprise_authenticator, random_user, expected_log):
    """Test that last_login_from is set correctly when multiple authenticators are present."""
    # Add last_login_from attribute to user
    random_user.last_login_from = None

    # Create mock authenticator plugin objects with proper structure
    mock_github_plugin = mock.MagicMock()
    mock_github_plugin.authenticate.return_value = None
    mock_github_plugin.database_instance = github_enterprise_authenticator

    mock_local_plugin = mock.MagicMock()
    mock_local_plugin.authenticate.return_value = random_user
    mock_local_plugin.database_instance = local_authenticator

    # Mock the save method to track calls
    with mock.patch.object(random_user, 'save') as mock_save:
        with mock.patch(
            "ansible_base.authentication.backend.get_authentication_backends",
            return_value={github_enterprise_authenticator.id: mock_github_plugin, local_authenticator.id: mock_local_plugin},
        ):
            # Expected log message when user logs in
            with expected_log(
                'ansible_base.authentication.backend.logger',
                "info",
                f'User {random_user.username} logged in from authenticator with ID "{local_authenticator.id}"',
            ):
                auth_return = backend.AnsibleBaseAuth().authenticate(None)

            # Verify the user is returned
            assert auth_return == random_user

            # Verify last_login_from was set to the local authenticator (the one that succeeded)
            assert random_user.last_login_from == local_authenticator

            # Verify save was called with the correct update_fields
            mock_save.assert_called_once_with(update_fields=['last_login_from'])


@pytest.mark.django_db
def test_last_login_from_inactive_user(local_authenticator, random_user):
    """Test that last_login_from is not set when user is inactive."""
    # Add last_login_from attribute to user but make user inactive
    random_user.last_login_from = None
    random_user.is_active = False

    # Create a mock authenticator plugin object with proper structure
    mock_authenticator_plugin = mock.MagicMock()
    mock_authenticator_plugin.authenticate.return_value = random_user
    mock_authenticator_plugin.database_instance = local_authenticator

    # Mock the save method to track calls
    with mock.patch.object(random_user, 'save') as mock_save:
        with mock.patch(
            "ansible_base.authentication.backend.get_authentication_backends",
            return_value={local_authenticator.id: mock_authenticator_plugin},
        ):
            auth_return = backend.AnsibleBaseAuth().authenticate(None)

            # Verify authentication failed (returns None for inactive user)
            assert auth_return is None

            # Verify save was never called since authentication failed
            mock_save.assert_not_called()

            # Verify last_login_from was not changed
            assert random_user.last_login_from is None


@pytest.mark.django_db
def test_last_login_from_social_auth_failed(local_authenticator, random_user):
    """Test that last_login_from is not set when social auth pipeline fails."""
    # Add last_login_from attribute to user
    random_user.last_login_from = None

    # Create a mock authenticator plugin object with proper structure
    mock_authenticator_plugin = mock.MagicMock()
    mock_authenticator_plugin.authenticate.return_value = SOCIAL_AUTH_PIPELINE_FAILED_STATUS
    mock_authenticator_plugin.database_instance = local_authenticator

    # Mock the save method to track calls
    with mock.patch.object(random_user, 'save') as mock_save:
        with mock.patch(
            "ansible_base.authentication.backend.get_authentication_backends",
            return_value={local_authenticator.id: mock_authenticator_plugin},
        ):
            auth_return = backend.AnsibleBaseAuth().authenticate(None)

            # Verify authentication failed (returns None)
            assert auth_return is None

            # Verify save was never called since authentication failed
            mock_save.assert_not_called()

            # Verify last_login_from was not changed
            assert random_user.last_login_from is None
