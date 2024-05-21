import logging
import re
from datetime import datetime, timedelta
from functools import partial
from unittest import mock
from uuid import uuid4

import pytest
from django.test.utils import override_settings
from jwt.exceptions import DecodeError
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.jwt_consumer.common.auth import JWTAuthentication, JWTCommonAuth, default_mapped_user_fields
from ansible_base.jwt_consumer.common.cert import JWTCert, JWTCertException
from ansible_base.lib.utils.translations import translatableConditionally as _
from ansible_base.rbac.models import RoleDefinition
from ansible_base.resource_registry.models import Resource
from test_app.models import Organization, Team

default_logger = 'ansible_base.jwt_consumer.common.auth.logger'


@pytest.fixture
def organization_admin_role():
    from ansible_base.rbac.permission_registry import permission_registry
    from test_app.models import Organization

    role = RoleDefinition.objects.create_from_permissions(
        permissions=[
            permission_registry.team_permission,
            f'view_{permission_registry.team_model._meta.model_name}',
            'view_organization',
            'change_organization',
        ],
        name='Organization Admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        managed=True,
    )
    return role


class TestJWTCommonAuth:
    @pytest.mark.django_db
    def test_init(self):
        my_auth = JWTCommonAuth()
        assert my_auth.mapped_user_fields == default_mapped_user_fields
        new_user_fields = ["a", "b", "c"]
        my_auth = JWTCommonAuth(new_user_fields)
        assert my_auth.mapped_user_fields == new_user_fields

    @pytest.mark.django_db
    def test_parse_jwt_no_request(self):
        my_auth = JWTCommonAuth()
        assert my_auth.parse_jwt_token(None) is None

    @pytest.mark.django_db
    def test_parse_jwt_no_header(self, caplog, mocked_http, shut_up_logging):
        with caplog.at_level(logging.INFO):
            my_auth = JWTCommonAuth()
            my_auth.parse_jwt_token(mocked_http.mocked_parse_jwt_token_get_request('without_headers'))
            assert "X-DAB-JW-TOKEN header not set for JWT authentication" in caplog.text

    @pytest.mark.django_db
    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'test_app'])
    def test_parse_jwt_happy_path(self, mocked_http, test_encryption_public_key, shut_up_logging, jwt_token):
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            my_auth = JWTCommonAuth()
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
            my_auth.parse_jwt_token(request)
            user = my_auth.user
            assert my_auth.token == jwt_token.unencrypted_token
            assert user.username == jwt_token.unencrypted_token['user_data']['username']
            assert user.first_name == jwt_token.unencrypted_token['user_data']["first_name"]
            assert user.last_name == jwt_token.unencrypted_token['user_data']["last_name"]
            assert user.email == jwt_token.unencrypted_token['user_data']["email"]
            assert user.is_superuser == jwt_token.unencrypted_token['user_data']["is_superuser"]

    @pytest.mark.django_db
    def test_parse_jwt_no_jwt_key(self, mocked_http, caplog):
        my_auth = JWTCommonAuth()
        request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
        with caplog.at_level(logging.INFO):
            my_auth.parse_jwt_token(request)
            assert my_auth.user is None
            assert my_auth.token is None
            assert 'Failed to get the setting ANSIBLE_BASE_JWT_KEY' in caplog.text

    @pytest.mark.django_db
    def test_log_exception_no_expansion(self, expected_log):
        common_auth = JWTCommonAuth()
        message = "This is a test"
        translated_message = 'Translated text'
        expected_log = partial(expected_log, default_logger)
        with mock.patch('ansible_base.lib.utils.translations.translatableConditionally.translated', return_value=translated_message):
            with expected_log("error", message):
                with pytest.raises(AuthenticationFailed, match=translated_message):
                    common_auth.log_and_raise(_(message))

    @pytest.mark.django_db
    def test_log_exception_with_expansion(self, expected_log):
        common_auth = JWTCommonAuth()
        message = "Please make sure this is %(expanded)s"
        translated_message = 'Translated with %(expanded)s text'
        expansion_values = {'expanded': 'whatever'}
        expected_log = partial(expected_log, default_logger)
        with mock.patch('ansible_base.lib.utils.translations.translatableConditionally.translated', return_value=translated_message):
            with expected_log("error", message % expansion_values):
                with pytest.raises(AuthenticationFailed, match=translated_message % expansion_values):
                    common_auth.log_and_raise(_(message), expansion_values)

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'user_fields,token,should_save',
        [
            # Everything is the same
            ({'first_name': 'Cindy', 'last_name': 'Lou'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, False),
            # Update because the user has old data
            ({'first_name': 'Cindy', 'last_name': 'Liu'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, True),
            # Update from multiple properties
            ({'first_name': 'Billy', 'last_name': 'Bob'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, True),
            # Extra tokens in the user are irrelevant
            ({'first_name': 'Cindy', 'last_name': 'Lou', 'email': 'test'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, False),
            ({'first_name': 'Billy', 'last_name': 'Bob', 'email': 'test'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, True),
            # New properties in the token
            ({'first_name': 'Cindy', 'last_name': 'Lou'}, {'first_name': 'Cindy', 'last_name': 'Lou', 'email': 'test'}, True),
        ],
    )
    def test_map_user_fields(self, user_fields, token, should_save, caplog, shut_up_logging):
        user = mock.Mock(unsername='Bob', **user_fields)
        common_auth = JWTCommonAuth()
        common_auth.map_fields = ['first_name', 'last_name']
        common_auth.user = user
        common_auth.token = token
        with caplog.at_level(logging.INFO):
            common_auth.map_user_fields()
            if should_save:
                assert f"Saving user {user.username}" in caplog.text
                assert user.save.called

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "remove,is_user_data_entry",
        [
            ("sub", False),
            ("user_data", False),
            ("username", True),
            ("first_name", True),
            ("last_name", True),
            ("email", True),
            ("is_superuser", True),
            ("iss", False),
            ("exp", False),
            ("aud", False),
            ("objects", False),
            ("object_roles", False),
            ("global_roles", False),
        ],
    )
    def test_validate_token_missing_default_items(self, remove, is_user_data_entry, jwt_token, test_encryption_public_key):
        # Remove the element we are testing
        if is_user_data_entry:
            del jwt_token.unencrypted_token['user_data'][remove]
        else:
            del jwt_token.unencrypted_token[remove]

        # Test the function
        common_auth = JWTCommonAuth()

        if is_user_data_entry:
            exception_text = f"JWT did not have proper user_data, missing fields: {remove}"
        else:
            exception_text = f'Failed to decrypt JWT: Token is missing the "{remove}" claim'

        with pytest.raises(AuthenticationFailed, match=exception_text):
            common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)

    @pytest.mark.django_db
    def test_validate_token_expired_token(self, jwt_token, test_encryption_public_key):
        jwt_token.unencrypted_token['exp'] = datetime.now() + timedelta(minutes=-10)
        # Test the function
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match="JWT has expired"):
            common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "item,exception",
        [
            ("iss", "JWT did not come from the correct issuer"),
            ("aud", "JWT did not come for the correct audience"),
        ],
    )
    def test_validate_token_invalid_items(self, item, exception, jwt_token, test_encryption_public_key):
        # Replace the item with 'junk'
        jwt_token.unencrypted_token[item] = "Junk"
        # Encrypt the token
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match=exception):
            common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "token,key,exception_text",
        [
            (None, None, "Invalid token type. Token must be a <class 'bytes'>"),
            ("", None, "Not enough segments"),
            (None, "", "Invalid token type. Token must be a <class 'bytes'>"),
            ("junk", "junk", "Not enough segments"),
            ("a.b.c", None, "Invalid header padding"),
        ],
    )
    def test_validate_token_with_junk_input(self, token, key, exception_text):
        common_auth = JWTCommonAuth()
        with pytest.raises(DecodeError, match=exception_text):
            common_auth.validate_token(token, key)

    @pytest.mark.django_db
    def test_validate_token_random_exception(self):
        # Encrypt the token
        common_auth = JWTCommonAuth()
        exception = IOError('blah')
        with mock.patch('jwt.decode') as decode_function:
            decode_function.side_effect = exception
            exception_text = re.escape(f"Unknown error occurred decrypting JWT ({exception.__class__}) {exception}")
            with pytest.raises(AuthenticationFailed, match=exception_text):
                common_auth.validate_token(None, None)

    @pytest.mark.django_db
    def test_validate_token_valid_token(self, jwt_token, test_encryption_public_key):
        # Test the function
        common_auth = JWTCommonAuth()
        parsed_token = common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)
        assert parsed_token == jwt_token.unencrypted_token

    @pytest.mark.django_db
    @mock.patch('ansible_base.jwt_consumer.common.auth.JWTCert.get_decryption_key', side_effect=JWTCertException('testing'))
    def test_cert_exception_converts_to_AuthenticationFailed(self, get_decryption_key, mocked_http):
        with pytest.raises(AuthenticationFailed):
            common_auth = JWTCommonAuth()
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
            common_auth.parse_jwt_token(request)

    # If other tests are running at the same time there is a chance that they might set the key in the cache.
    # Since we don't mock the response intentionally we are going to tell this test to use a different cache key
    @pytest.mark.django_db
    @mock.patch('ansible_base.jwt_consumer.common.cache.cache_key', 'test_cert_fails_decryption_from_uncached_key')
    def test_cert_fails_decryption_from_uncached_key(self, mocked_http, expected_log, test_encryption_public_key):
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.validate_token', side_effect=DecodeError('validation always fails')):
                common_auth = JWTCommonAuth()
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                expected_log = partial(expected_log, "ansible_base.jwt_consumer.common.auth.logger")
                with expected_log("error", 'check your key and generated token'):
                    with pytest.raises(AuthenticationFailed):
                        common_auth.parse_jwt_token(request)

    @pytest.mark.django_db
    def test_cert_fails_decryption_first_key_bad_second_key_good(self, mocked_http, expected_log, test_encryption_public_key, random_public_key):
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
            # Get the bad decryption key into the cache
            cert = JWTCert()
            cert.get_decryption_key()
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            common_auth = JWTCommonAuth()
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
            common_auth.parse_jwt_token(request)

    def test_cert_fails_decryption_from_cached_key_but_key_is_invalid(self, mocked_http, expected_log, test_encryption_public_key):
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            # Get the decryption key into the cache
            cert = JWTCert()
            cert.get_decryption_key()

            # Same test as above
            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.validate_token', side_effect=DecodeError('validation always fails')):
                common_auth = JWTCommonAuth()
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                expected_log = partial(expected_log, "ansible_base.jwt_consumer.common.auth.logger")
                with expected_log("error", 'cached key was correct'):
                    with pytest.raises(AuthenticationFailed):
                        common_auth.parse_jwt_token(request)

    @pytest.mark.parametrize(
        "token,logs_error",
        [
            ({}, None),
            ({"global_roles": ['System Auditor']}, False),
            ({"global_roles": ['Junk']}, True),
        ],
    )
    def test_process_rbac_permissions_system_roles(self, token, logs_error, admin_user, expected_log):
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = token
        if logs_error:
            with expected_log(default_logger, 'error', 'Unable to grant'):
                authentication.process_rbac_permissions()
        elif logs_error is not None:
            # Make sure we have a System Auditor role
            RoleDefinition.objects.get_or_create(
                name='System Auditor',
                defaults={
                    'description': 'Migrated singleton role giving read permission to everything',
                    'managed': True,
                },
            )
            with expected_log(default_logger, 'info', 'Granted user'):
                authentication.process_rbac_permissions()
        else:
            authentication.process_rbac_permissions()

    def test_process_rbac_permissions_object_roles_role_dne(self, expected_log, admin_user):
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {'object_roles': {'Junk': ['a']}}
        with expected_log(default_logger, 'error', 'Unable to grant'):
            authentication.process_rbac_permissions()

    def test_process_rbac_permissions_object_role_exists_object_exists(self, expected_log, admin_user, organization, organization_admin_role):
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {
            'objects': {'organization': [{'ansible_id': organization.resource.ansible_id, 'name': organization.name}]},
            'object_roles': {organization_admin_role.name: {'content_type': 'organization', 'objects': [0]}},
        }
        with expected_log(default_logger, 'info', 'with ansible_id'):
            authentication.process_rbac_permissions()

    @pytest.mark.django_db
    def test_get_or_create_resource_invalid_content_type(self):
        authentication = JWTCommonAuth()
        assert authentication.get_or_create_resource('junk', {'ansible_id': uuid4()}) == (None, None)

    @pytest.mark.django_db
    def test_get_or_create_resource_organization(self):
        authentication = JWTCommonAuth()
        data = {'ansible_id': uuid4(), 'name': 'Test Organization'}
        assert not Organization.objects.filter(name=data['name']).exists()
        assert not Resource.objects.filter(ansible_id=data['ansible_id']).exists()
        resource, obj = authentication.get_or_create_resource('organization', data)
        assert resource is not None and obj is not None
        assert Organization.objects.filter(name=data['name']).exists()
        assert Resource.objects.filter(ansible_id=data['ansible_id']).exists()

    @pytest.mark.django_db
    def test_get_or_create_resource_team(self):
        authentication = JWTCommonAuth()
        org_name = 'Testing Org Name'
        authentication.token = {
            'objects': {
                'organization': [
                    {
                        'ansible_id': str(uuid4()),
                        'name': org_name,
                    }
                ]
            },
        }
        data = {
            'ansible_id': uuid4(),
            'name': 'Test Team',
            'org': 0,
        }
        assert not Team.objects.filter(name=data['name']).exists()
        assert not Organization.objects.filter(name=org_name).exists()
        assert not Resource.objects.filter(ansible_id=data['ansible_id']).exists()
        resource, obj = authentication.get_or_create_resource('team', data)
        assert resource is not None and obj is not None
        assert Organization.objects.filter(name=org_name).exists()
        assert Resource.objects.filter(ansible_id=data['ansible_id']).exists()
        assert Team.objects.filter(name=data['name']).exists()


class TestJWTAuthentication:
    def test_authenticate(self, jwt_token, django_user_model, mocked_http, test_encryption_public_key):
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            user = django_user_model.objects.create_user(username=jwt_token.unencrypted_token['sub'], password="password")
            jwt_auth = JWTAuthentication()
            jwt_auth.common_auth.user = user
            jwt_auth.common_auth.token = jwt_token.unencrypted_token
            jwt_auth.process_user_data()
            # This double call causes line 140 `if user_needs_save` to return false
            jwt_auth.process_user_data()
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
            created_user, _ = jwt_auth.authenticate(request)
            assert user == created_user

    def test_authenticate_no_user(self, user):
        with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.parse_jwt_token') as mock_parse:
            mock_parse.return_value = (None, None)
            jwt_auth = JWTAuthentication()
            auth_provided = jwt_auth.authenticate(mock.MagicMock())
            assert auth_provided is None

    @pytest.mark.django_db()
    def test_process_user_data(self):
        with mock.patch("ansible_base.jwt_consumer.common.auth.JWTCommonAuth.map_user_fields") as mock_inspect:
            jwt_auth = JWTAuthentication()
            jwt_auth.process_user_data()
            mock_inspect.assert_called()

    @pytest.mark.django_db
    def test_process_permissions(self, caplog, shut_up_logging):
        with caplog.at_level(logging.INFO):
            jwt_auth = JWTAuthentication()
            jwt_auth.process_permissions()
            assert "process_permissions was not overridden for JWTAuthentication" in caplog.text

    @pytest.mark.django_db
    def test_raise_an_exception_if_the_key_is_not_cached(self, random_public_key, mocked_http, create_mock_method):
        mock_field_dicts = [
            {"key": random_public_key, "cached": False},
        ]
        # We are going to return a key which will not work with jwt_token provided by mocked_http
        # Because its not cached the call to parse_jwt_token should raise the exception
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCert.get_decryption_key', create_mock_method(mock_field_dicts)):
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                jwt_auth = JWTAuthentication()
                with pytest.raises(AuthenticationFailed) as af:
                    jwt_auth.authenticate(request)
                    assert 'check your key and generated token' in af
                    assert 'cached key was correct' not in af

    def test_raise_an_exception_if_the_key_is_cached_but_the_new_key_is_the_same(self, random_public_key, mocked_http, create_mock_method):
        # We are going to:
        #     1. return a key which will not work with jwt_token provided by mocked_http
        #     2. Cache a key that is invalid
        #     3. Error when the new token is the same as the cached token

        mock_field_dicts = [
            {"key": random_public_key, "cached": True},
            {"key": random_public_key, "cached": False},
        ]

        # Pretend the key is coming from a URL
        url = 'https://example.com'
        with override_settings(ANSIBLE_BASE_JWT_KEY=url):
            # 1. Make the get_decryption_key always return the random key (which is invalid) && 2. pretend the key is cached
            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCert.get_decryption_key', create_mock_method(mock_field_dicts)):
                # 3. Make the call.
                # This will attempt to use the cached key, recognize that its invalid, load the key again (which will be the same) and then error out
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                jwt_auth = JWTAuthentication()
                with pytest.raises(AuthenticationFailed) as af:
                    jwt_auth.authenticate(request)
                    assert 'check your key and generated token' in af
                    assert 'cached key was correct' in af

    def test_correctly_authenticate_if_the_cached_key_is_invalid_but_the_new_key_is_correct(
        self, random_public_key, mocked_http, test_encryption_public_key, django_user_model, jwt_token, create_mock_method
    ):
        # Pretend the key is coming from a URL
        url = 'https://example.com'
        with override_settings(ANSIBLE_BASE_JWT_KEY=url):
            jwt_cert_field_changes = [
                {"key": random_public_key, "cached": True},
                {"key": test_encryption_public_key, "cached": False},
            ]

            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCert.get_decryption_key', create_mock_method(jwt_cert_field_changes)):
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                jwt_auth = JWTAuthentication()
                user = django_user_model.objects.create_user(username=jwt_token.unencrypted_token['user_data']['username'], password="password")
                created_user, _ = jwt_auth.authenticate(request)
                assert created_user == user

    def test_user_logging_in_and_in_cache_but_deleted_in_db(self, mocked_http, django_user_model, jwt_token, test_encryption_public_key):
        user = django_user_model.objects.create_user(username=jwt_token.unencrypted_token['user_data']['username'], password="password")
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            jwt_auth = JWTAuthentication()
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')

            # Get the user into the cache
            user_object, created = jwt_auth.authenticate(request)
            assert user_object == user

            # delete the user from the DB
            user.delete()

            # Authenticate the user again which will recreate the user so the objects will no longer be the same
            user_object, _ = jwt_auth.authenticate(request)
            assert user_object.username == user.username
            assert user_object.id != user.id

    def test_failure_when_cached_key_incorrect_and_actual_key_raises_exception(self, random_public_key, mocked_http, django_user_model, jwt_token, caplog):
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):

            def change_cert_key_value(self, ignore_cache=False):
                if ignore_cache:
                    raise JWTCertException()

                self.key = random_public_key
                self.cached = not ignore_cache
                return None

            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCert.get_decryption_key', change_cert_key_value):
                with pytest.raises(AuthenticationFailed):
                    request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                    jwt_auth = JWTAuthentication()
                    jwt_auth.authenticate(request)

    @pytest.mark.django_db
    def test_jwt_authentication_with_common_auth_processing(self):
        with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.process_rbac_permissions') as mp:
            authentication = JWTAuthentication()
            authentication.use_rbac_permissions = True
            authentication.process_permissions()
            mp.assert_called_once()
