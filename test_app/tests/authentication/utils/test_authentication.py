import pytest
from django.conf import settings
from django.test import override_settings
from social_core.exceptions import AuthException

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils import authentication
from ansible_base.lib.utils.response import get_relative_url
from test_app.models import User


def load_social_auth_settings():
    return {"SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL": settings.SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL}


@pytest.mark.django_db
class TestAuthenticationUtilsAuthentication:
    logger = 'ansible_base.authentication.utils.authentication.logger'

    @pytest.mark.parametrize(
        "name, exp_val, username_is_full_email_setting",
        [
            ("USER_FIELDS", ["username", "email"], False),
            ("SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL", True, True),
            ("SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL", False, False),
            ("BOGUS", None, False),
        ],
    )
    def test_fake_backend_settings(self, name, exp_val, username_is_full_email_setting):
        with override_settings(SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL=username_is_full_email_setting):
            with override_settings(
                ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION="test_app.tests.authentication.utils.test_authentication.load_social_auth_settings"
            ):
                backend = authentication.FakeBackend()
                response = backend.setting(name)
                assert response == exp_val

    def test_fake_backend_settings_with_default(self):
        backend = authentication.FakeBackend()
        response = backend.setting("BOGUS", "bogus_default")
        assert response == "bogus_default"

    def test_get_local_username_no_input(self):
        response = authentication.get_local_username({})
        assert response is not None

    def test_get_local_user_username_existing_user(self, random_user):
        response = authentication.get_local_username({'username': random_user.username})
        assert len(response) > len(random_user.username)

    @pytest.mark.parametrize(
        "username_is_full_email_setting, expected_username",
        [
            (True, "new-user@example.com"),
            (False, "new-user"),
        ],
    )
    def test_get_local_username_with_email(self, username_is_full_email_setting, expected_username):
        user_details = {'username': 'new-user', 'email': 'new-user@example.com'}
        with override_settings(SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL=username_is_full_email_setting):
            with override_settings(
                ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION="test_app.tests.authentication.utils.test_authentication.load_social_auth_settings"
            ):
                response = authentication.get_local_username(user_details)
                assert response == expected_username

    @pytest.mark.parametrize(
        "related_authenticator,info_message,expected_username",
        [
            (None, 'is able to authenticate user', True),
            ('local', 'already authenticated', True),
            ('ldap', 'is already associated with an existing user, creating a new user with username', False),
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
        # Use different log levels based on the scenario
        log_level = 'warning' if related_authenticator == 'ldap' else 'info'
        with expected_log(self.logger, log_level, info_message):
            new_username = authentication.determine_username_from_uid(uid=uid, email="", authenticator=local_authenticator)
            if expected_username:
                assert new_username == random_user.username
            else:
                assert len(new_username) > len(random_user.username)

    def test_determine_username_from_uid_behavior(self, local_authenticator, saml_authenticator):
        # Test when there's no collision
        new_username = authentication.determine_username_from_uid(uid="new-user", email="", authenticator=saml_authenticator)
        assert new_username == "new-user"

        # Create a different user tied to the same authenticator to force a collision
        existing_user = User.objects.create(username="existing-user")
        AuthenticatorUser.objects.create(user=existing_user, provider=saml_authenticator, uid="existing-user")

        # Test when there is a match (same uid and authenticator)
        new_username = authentication.determine_username_from_uid(uid="existing-user", email="", authenticator=saml_authenticator)
        assert new_username == "existing-user", "There should not have been a collision "

        # Test with a different authenticator (should return a new username)
        new_username = authentication.determine_username_from_uid(uid="existing-user", email="", authenticator=local_authenticator)
        assert new_username != "existing-user"
        assert new_username.startswith("existing-user")  # It should be "existing-user" followed by a hash

    def test_username_collision_scenario(self, admin_user, admin_api_client, saml_authenticator):
        # We are going to play around with two uids
        user1_uid = 'user-1'
        user2_uid = "user-2"

        # Step 1: Create an external user with username 'user-1' through the API
        user1, _, user1_created = authentication.get_or_create_authenticator_user(
            uid=user1_uid, email="", authenticator=saml_authenticator, user_details={}, extra_data={}
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
        throw_away_user2_username = authentication.determine_username_from_uid(uid=user2_uid, email="", authenticator=saml_authenticator)
        assert throw_away_user2_username != user2_uid, "Newly selected username matches conflicting username"
        assert throw_away_user2_username.startswith(user2_uid)  # It should be "user-2" followed by a hash
        # We have not changed the AuthenticatorUser table here, just confirmed that if we try
        #    to authenticate with user-2 we will end up with a different user name because
        #    there is already a user in the system with username user-2

        # Attempt to create the new user
        user2_user, _, user2_created = authentication.get_or_create_authenticator_user(
            uid=user2_uid, email="", authenticator=saml_authenticator, user_details={}, extra_data={}
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
            authentication.determine_username_from_uid(uid=uid, email="", authenticator=authenticator)
        with pytest.raises(AuthException):
            authentication.get_or_create_authenticator_user(uid=uid, email="", authenticator=authenticator, user_details={}, extra_data={})

    #
    # Tests for get_or_create_authenticator_user (gocau)
    #

    def test_gocau_auth_user_exists(self, random_user, local_authenticator):
        au = AuthenticatorUser.objects.create(uid=random_user.username, provider=local_authenticator, user=random_user)
        local_user, auth_user, created = authentication.get_or_create_authenticator_user(
            uid=random_user.username, email="", authenticator=local_authenticator, user_details={}, extra_data={}
        )
        assert created is False
        assert local_user == random_user
        assert auth_user == au

    def test_gocau_auth_user_exists_from_another_provider(self, random_user, local_authenticator, ldap_authenticator):
        orig_au = AuthenticatorUser.objects.create(uid=random_user.username, provider=ldap_authenticator, user=random_user)
        local_user, auth_user, created = authentication.get_or_create_authenticator_user(
            uid=random_user.username, email="", authenticator=local_authenticator, user_details={'username': random_user.username}, extra_data={}
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
                local_user, auth_user, created = authentication.get_or_create_authenticator_user(
                    uid=username, email="", authenticator=ldap_authenticator, user_details={}, extra_data={}
                )
        else:
            with expected_log(self.logger, 'info', 'created User'):
                with expected_log(self.logger, 'debug', f'created AuthenticatorUser for {username}'):
                    local_user, auth_user, created = authentication.get_or_create_authenticator_user(
                        uid=username, email="", authenticator=ldap_authenticator, user_details={}, extra_data={}
                    )

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
        response = authentication.determine_username_from_uid_social(
            details={'username': 'Bob'},
            backend=get_authenticator_class(ldap_authenticator.type)(database_instance=ldap_authenticator),
            uid="Bob",
        )
        assert response == {'username': 'Bob'}

    def test_raise_auth_exception(self):
        try:
            authentication.raise_auth_exception('testing')
        except AuthException as e:
            assert str(e) == 'testing'

    def test_raise_auth_exception_in_logs(self, local_authenticator, expected_log):
        with expected_log(
            'ansible_base.authentication.utils.authentication.logger',
            'warning',
            'AuthException: System user is not allowed to log in from external authentication sources.',
        ):
            try:
                authentication.get_or_create_authenticator_user(
                    uid=settings.SYSTEM_USERNAME, email="", authenticator=local_authenticator, user_details={}, extra_data={}
                )
            except AuthException:
                pass

    @pytest.mark.parametrize(
        "uid_param, expected_uid_filter",
        [
            ("user123", ["testuser", "user123"]),  # When uid is provided, should include both selected_username and uid
            (None, ["testuser"]),  # When uid is None, should only include selected_username
            ("", ["testuser"]),  # When uid is empty string, should only include selected_username
        ],
    )
    def test_determine_username_from_uid_social_uid_filter_construction(self, ldap_authenticator, uid_param, expected_uid_filter):
        """Test that uid_filter is constructed correctly in determine_username_from_uid_social."""
        from unittest.mock import patch

        authenticator_class = get_authenticator_class(ldap_authenticator.type)(database_instance=ldap_authenticator)

        # Mock migrate_from_existing_authenticator to return None (no migration)
        # Mock determine_username_from_uid to capture the uid_filter parameter
        with patch('ansible_base.authentication.utils.authentication.migrate_from_existing_authenticator') as mock_migrate:
            mock_migrate.return_value = None

            with patch('ansible_base.authentication.utils.authentication.determine_username_from_uid') as mock_determine_uid:
                mock_determine_uid.return_value = 'testuser'

                kwargs = {
                    'details': {'username': 'testuser', 'email': 'test@example.com'},
                    'backend': authenticator_class,
                }
                if uid_param is not None:
                    kwargs['uid'] = uid_param

                response = authentication.determine_username_from_uid_social(**kwargs)

                # Verify determine_username_from_uid was called with correct uid_filter
                mock_determine_uid.assert_called_once_with(
                    uid='testuser', uid_filter=expected_uid_filter, email='test@example.com', authenticator=ldap_authenticator
                )
                assert response == {'username': 'testuser'}

    def test_determine_username_from_uid_social_uid_filter_with_email_username(self, ldap_authenticator):
        """Test uid_filter construction when USERNAME_IS_FULL_EMAIL is True."""
        from unittest.mock import patch

        authenticator_class = get_authenticator_class(ldap_authenticator.type)(database_instance=ldap_authenticator)

        # Mock migrate_from_existing_authenticator to return None (no migration)
        # Mock the setting method to return True for USERNAME_IS_FULL_EMAIL
        with patch('ansible_base.authentication.utils.authentication.migrate_from_existing_authenticator') as mock_migrate:
            mock_migrate.return_value = None

            with patch.object(authenticator_class, 'setting') as mock_setting:
                mock_setting.return_value = True

                with patch('ansible_base.authentication.utils.authentication.determine_username_from_uid') as mock_determine_uid:
                    mock_determine_uid.return_value = 'user@example.com'

                    response = authentication.determine_username_from_uid_social(
                        details={'username': 'testuser', 'email': 'user@example.com'}, backend=authenticator_class, uid='uid123'
                    )

                    # When USERNAME_IS_FULL_EMAIL is True, selected_username should be the email
                    mock_determine_uid.assert_called_once_with(
                        uid='user@example.com', uid_filter=['user@example.com', 'uid123'], email='user@example.com', authenticator=ldap_authenticator
                    )
                    assert response == {'username': 'user@example.com'}

    def test_determine_username_from_uid_social_uid_filter_no_migration(self, ldap_authenticator):
        """Test that uid_filter is passed to determine_username_from_uid when migration doesn't occur."""
        from unittest.mock import patch

        authenticator_class = get_authenticator_class(ldap_authenticator.type)(database_instance=ldap_authenticator)

        with patch('ansible_base.authentication.utils.authentication.migrate_from_existing_authenticator') as mock_migrate:
            mock_migrate.return_value = None  # No migration

            with patch('ansible_base.authentication.utils.authentication.determine_username_from_uid') as mock_determine_uid:
                mock_determine_uid.return_value = 'finaluser'

                response = authentication.determine_username_from_uid_social(
                    details={'username': 'originaluser', 'email': 'test@example.com'}, backend=authenticator_class, uid='uid456'
                )

                # Verify migration was attempted first
                mock_migrate.assert_called_once_with(uid='uid456', alt_uid=None, authenticator=ldap_authenticator, preferred_username='originaluser')

                # Verify determine_username_from_uid was called with correct uid_filter
                mock_determine_uid.assert_called_once_with(
                    uid='originaluser', uid_filter=['originaluser', 'uid456'], email='test@example.com', authenticator=ldap_authenticator
                )
                assert response == {'username': 'finaluser'}

    def test_determine_username_from_uid_social_uid_filter_with_migration(self, ldap_authenticator):
        """Test that determine_username_from_uid is not called when migration succeeds."""
        from unittest.mock import patch

        authenticator_class = get_authenticator_class(ldap_authenticator.type)(database_instance=ldap_authenticator)

        with patch('ansible_base.authentication.utils.authentication.migrate_from_existing_authenticator') as mock_migrate:
            mock_migrate.return_value = 'migrated_user'  # Migration succeeded

            with patch('ansible_base.authentication.utils.authentication.determine_username_from_uid') as mock_determine_uid:
                response = authentication.determine_username_from_uid_social(
                    details={'username': 'originaluser', 'email': 'test@example.com'}, backend=authenticator_class, uid='uid789'
                )

                # Verify migration was attempted
                mock_migrate.assert_called_once_with(uid='uid789', alt_uid=None, authenticator=ldap_authenticator, preferred_username='originaluser')

                # determine_username_from_uid should NOT be called when migration succeeds
                mock_determine_uid.assert_not_called()
                assert response == {'username': 'migrated_user'}
