import pytest
from django.conf import settings
from social_core.exceptions import AuthException

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils import authentication
from ansible_base.lib.utils.response import get_relative_url
from test_app.models import User


@pytest.mark.django_db
class TestAuthenticationUtilsAuthentication:
    logger = 'ansible_base.authentication.utils.authentication.logger'

    def test_fake_backend_settings(self):
        backend = authentication.FakeBackend()
        response = backend.setting()
        assert response == ["username", "email"]

    def test_get_local_username_no_input(self):
        response = authentication.get_local_username({})
        assert response is not None

    def test_get_local_user_username_existing_user(self, random_user):
        response = authentication.get_local_username({'username': random_user.username})
        assert len(response) > len(random_user.username)

    @pytest.mark.parametrize(
        "related_authenticator,info_message,expected_username",
        [
            (None, 'is able to authenticate user', True),
            ('local', 'already authenticated', True),
            ('ldap', 'username is already in use by another authenticator', False),
            ('multiple', 'already authenticated', True),
        ],
    )
    def test_determine_username_from_uid(
        self, related_authenticator, info_message, expected_username, random_user, local_authenticator, ldap_authenticator, expected_log
    ):
        uid = random_user.username
        if related_authenticator in ['local', 'multiple']:
            AuthenticatorUser.objects.create(uid=random_user.username, user=random_user, provider=local_authenticator)
        elif related_authenticator in ['ldap', 'multiple']:
            AuthenticatorUser.objects.create(uid=random_user.username, user=random_user, provider=ldap_authenticator)
        with expected_log(self.logger, 'info', info_message):
            new_username = authentication.determine_username_from_uid(uid, local_authenticator)
            if expected_username:
                assert new_username == random_user.username
            else:
                assert len(new_username) > len(random_user.username)

    def test_determine_username_from_uid_behavior(self, local_authenticator, saml_authenticator):
        # Test when there's no collision
        new_username = authentication.determine_username_from_uid(uid="new-user", authenticator=saml_authenticator)
        assert new_username == "new-user"

        # Create a different user tied to the same authenticator to force a collision
        existing_user = User.objects.create(username="existing-user")
        AuthenticatorUser.objects.create(
            user=existing_user,
            provider=saml_authenticator,
            uid="existing-user"
        )

        # Test when there is a match (same uid and authenticator)
        new_username = authentication.determine_username_from_uid(uid="existing-user", authenticator=saml_authenticator)
        assert new_username == "existing-user", "There should not have been a collision "

        # Test with a different authenticator (should return a new username)
        new_username = authentication.determine_username_from_uid(uid="existing-user", authenticator=local_authenticator)
        assert new_username != "existing-user"
        assert new_username.startswith("existing-user")  # It should be "existing-user" followed by a hash

    def test_username_collision_scenario(self, admin_user, admin_api_client, saml_authenticator):
        # We are going to play around with two uids
        user1_uid = 'user-1'
        user2_uid = "user-2"

        # Step 1: Create an external user with username 'user-1' through the API
        user1, _, user1_created = authentication.get_or_create_authenticator_user(
            user1_uid, saml_authenticator, {}, {}
        )
        # This should now succeed because we're using a unique username
        assert user1.get_authenticator_uids() == [user1_uid]
        assert user1_created is True
        # In AuthenticatorUser table we now have: uid: user-1, username: user-1, authentciator: saml

        # Step 2: Change the username locally to 'user-2'
        url = get_relative_url("user-detail", kwargs={"pk": user1.pk})
        response = admin_api_client.patch(url, {"username": user2_uid})
        assert response.status_code == 200
        user1.refresh_from_db()
        assert user1.username == user2_uid, "Username did not properly get updated"
        assert user1.get_authenticator_uids() == [user1_uid], "The external UID changed!"  # The UID should not change for external authenticators
        # In AuthenticatorUser table we now have: uid: user-1, username: user-2, authentciator: saml

        # Step 3: Get the ID of a new user whose uid is "user-2"
        # We want to end up with: uid: user-1, username: user2<hash>, authenticator: local
        # The function should now return a different username due to collision
        throw_away_user2_username = authentication.determine_username_from_uid(uid=user2_uid, authenticator=saml_authenticator)
        assert throw_away_user2_username != user2_uid, "Newly selected username matches conflicting username"
        assert throw_away_user2_username.startswith(user2_uid)  # It should be "user-2" followed by a hash
        # We have not changed the AuthenticatorUser table here, just confirmed that if we try
        #    to authenticate with user-2 we will end up with a different user name because
        #    there is already a user in the system with username user-2

        # Attempt to create the new user
        user2_user, _, user2_created = authentication.get_or_create_authenticator_user(
            user2_uid, saml_authenticator, {}, {}
        )
        assert user2_user.username != user2_uid
        assert user2_user.get_authenticator_uids() == [user2_uid]
        assert user2_created is True

        # Verify that two users exist with usernames starting with "user-2"
        assert User.objects.filter(username__startswith=user2_uid).count() == 2

        # Verify the state of AuthenticatorUser entries
        assert AuthenticatorUser.objects.filter(uid=user1_uid, user__username=user2_uid).exists(), "Missing renamed user"
        assert AuthenticatorUser.objects.filter(uid=user2_uid, user__username=user2_user.username).exists(), "Missing newly created user"

    @pytest.mark.parametrize(
        "auth_fixture",
        [
            "local_authenticator",
            "ldap_authenticator",
            "keycloak_authenticator",
            "saml_authenticator",
            "oidc_authenticator",
            "tacacs_authenticator",
            "radius_authenticator",
        ],
    )
    def test_external_system_user_login(self, request, auth_fixture):
        uid = settings.SYSTEM_USERNAME
        authenticator = request.getfixturevalue(auth_fixture)
        with pytest.raises(AuthException):
            authentication.determine_username_from_uid(uid, authenticator)
        with pytest.raises(AuthException):
            authentication.get_or_create_authenticator_user(uid, authenticator, {}, {})

    #
    # Tests for get_or_create_authenticator_user (gocau)
    #

    def test_gocau_auth_user_exists(self, random_user, local_authenticator):
        au = AuthenticatorUser.objects.create(uid=random_user.username, provider=local_authenticator, user=random_user)
        local_user, auth_user, created = authentication.get_or_create_authenticator_user(random_user.username, local_authenticator, {}, {})
        assert created is False
        assert local_user == random_user
        assert auth_user == au

    def test_gocau_auth_user_exists_from_another_provider(self, random_user, local_authenticator, ldap_authenticator):
        orig_au = AuthenticatorUser.objects.create(uid=random_user.username, provider=ldap_authenticator, user=random_user)
        local_user, auth_user, created = authentication.get_or_create_authenticator_user(
            random_user.username, local_authenticator, {'username': random_user.username}, {}
        )
        assert created is True, "New AuthenticatorUser should have been created"
        assert local_user != random_user, "A new user should have been created"
        assert auth_user != orig_au, "Returned AuthenticatorUser matches the old"

    @pytest.mark.parametrize(
        "user_exists",
        (
            True,
            False,
        ),
    )
    def test_gocau_auth_user_needs_creation(self, user_exists, randname, ldap_authenticator, expected_log):
        username = randname('user')
        if user_exists:
            User.objects.create(username=username)
            with expected_log(self.logger, 'debug', f'created AuthenticatorUser for {username} attaching to existing user'):
                local_user, auth_user, created = authentication.get_or_create_authenticator_user(username, ldap_authenticator, {}, {})
        else:
            with expected_log(self.logger, 'info', 'created User'):
                with expected_log(self.logger, 'debug', f'created AuthenticatorUser for {username}'):
                    local_user, auth_user, created = authentication.get_or_create_authenticator_user(username, ldap_authenticator, {}, {})

        assert local_user is not None
        assert auth_user is not None
        assert created is True

    @pytest.mark.parametrize(
        "input",
        [
            None,
            {},
            {'details': {}},
            {'details': {'username': 'Jane'}},
        ],
    )
    def test_determine_username_from_uid_social_exception(self, input):
        with pytest.raises(AuthException):
            if input is None:
                authentication.determine_username_from_uid_social()
            else:
                authentication.determine_username_from_uid_social(**input)

    def test_determine_username_from_uid_social_happy_path(self, ldap_authenticator):
        response = authentication.determine_username_from_uid_social(details={'username': 'Bob'}, backend=ldap_authenticator)
        assert response == {'username': 'Bob'}
