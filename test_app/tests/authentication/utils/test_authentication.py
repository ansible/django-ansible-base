import pytest
from social_core.exceptions import AuthException

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils import authentication
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
            (None, 'is is able to authenticate user', True),
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
        AuthenticatorUser.objects.create(uid=random_user.username, provider=ldap_authenticator, user=random_user)
        local_user, auth_user, created = authentication.get_or_create_authenticator_user(
            random_user.username, local_authenticator, {'username': random_user.username}, {}
        )
        assert created is None
        assert local_user is None
        assert auth_user is None

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
