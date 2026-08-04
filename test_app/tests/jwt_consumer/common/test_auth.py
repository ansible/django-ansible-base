import logging
import re
from datetime import datetime, timedelta
from functools import partial
from unittest import mock
from uuid import uuid4

import pytest
from django.test.utils import override_settings
from jwt.exceptions import DecodeError
from rest_framework.exceptions import AuthenticationFailed, ValidationError

from ansible_base.jwt_consumer.common.auth import JWTAuthentication, JWTCommonAuth, RbacAwareJWTAuthentication, default_mapped_user_fields
from ansible_base.jwt_consumer.common.cert import JWTCert, JWTCertException
from ansible_base.jwt_consumer.common.exceptions import InvalidTokenException
from ansible_base.lib.utils.translations import translatableConditionally as _
from ansible_base.rbac.claims import get_or_create_resource, save_user_claims
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.resource_registry.models import Resource
from test_app.models import Organization, Team

default_logger = 'ansible_base.jwt_consumer.common.auth.logger'

claims_logger = 'ansible_base.rbac.claims.logger'


@pytest.fixture
def organization_admin_role():
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
        with caplog.at_level(logging.DEBUG):
            my_auth = JWTCommonAuth()
            my_auth.parse_jwt_token(mocked_http.mocked_parse_jwt_token_get_request('without_headers'))
            assert "X-DAB-JW-TOKEN header not set for JWT authentication" in caplog.text

    @pytest.mark.django_db
    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'test_app', 'ansible_base.resource_registry'])
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
    def test_map_user_fields_email_change_bypasses_rbac_policy(self, django_user_model):
        """JWT auth field sync must update email even when the RBAC email
        policy signal would block it for a regular requesting user.

        The pre_save signal rbac_pre_save_enforce_email_policy blocks email
        changes from non-privileged CRUM users.  map_user_fields() runs during
        JWT authentication (a trusted system operation), so it must bypass
        the signal by clearing the CRUM user via impersonate(None).
        """
        from crum import impersonate

        regular_user = django_user_model.objects.create_user(
            username='regular',
            password='password',
        )
        target_user = django_user_model.objects.create_user(
            username='jwt-synced',
            password='password',
            email='old@example.com',
        )

        common_auth = JWTCommonAuth()
        common_auth.user = target_user
        common_auth.token = {
            'user_data': {
                'username': 'jwt-synced',
                'first_name': '',
                'last_name': '',
                'email': 'new@example.com',
                'is_superuser': False,
            }
        }

        # Precondition: prove the signal blocks a direct save under this user
        with impersonate(regular_user):
            target_user.email = 'new@example.com'
            with pytest.raises(ValidationError, match="permission to change the email"):
                target_user.save()

        target_user.refresh_from_db()
        assert target_user.email == 'old@example.com', "precondition: direct save should have been blocked"

        # The actual test: map_user_fields bypasses the signal via impersonate(None)
        with impersonate(regular_user):
            common_auth.map_user_fields()

        target_user.refresh_from_db()
        assert target_user.email == 'new@example.com'

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
            ("claims_hash", False),
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
        with pytest.raises(InvalidTokenException) as excinfo:
            common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)

        assert "JWT expired" in str(excinfo.value)
        assert "check for clock skew" in str(excinfo.value)
        assert "Request ID" in str(excinfo.value)

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

    @pytest.mark.django_db
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
        "global_roles,logs_error",
        [
            ([], None),
            (['System Auditor'], False),
            (['Ext Auditor'], False),  # must dynamically create
            (['Unmanaged Auditor'], True),  # must dynamically create
            (['Junk'], True),
        ],
    )
    def test_apply_rbac_permissions_system_roles(
        self, global_roles, logs_error, admin_user, expected_log, external_auditor_constructor, unmanaged_external_auditor_constructor
    ):
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        if logs_error:
            with expected_log(claims_logger, 'error', 'Unable to grant'):
                save_user_claims(authentication.user, {}, {}, global_roles)
        elif logs_error is not None:
            # Make sure we have a System Auditor role
            RoleDefinition.objects.get_or_create(
                name='System Auditor',
                defaults={
                    'description': 'Migrated singleton role giving read permission to everything',
                    'managed': True,
                },
            )
            with expected_log(claims_logger, 'info', 'Granting user'):
                save_user_claims(authentication.user, {}, {}, global_roles)
        else:
            save_user_claims(authentication.user, {}, {}, global_roles)

    def test_apply_rbac_permissions_object_roles_role_dne(self, expected_log, admin_user):
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        object_roles = {'Junk': ['a']}
        with expected_log(claims_logger, 'error', 'Unable to grant'):
            save_user_claims(authentication.user, {}, object_roles, [])

    @pytest.mark.parametrize(
        "object_roles,log_level,log_substring",
        [
            ({"Organization Admin": {'content_type': 'organization', 'objects': [0]}}, "info", "with ansible_id"),
            ({"Cow Admin": {'content_type': 'organization', 'objects': [0]}}, "error", "Unable to grant"),
        ],
    )
    def test_apply_rbac_permissions_object_role_exists_object_exists(
        self, object_roles, log_level, log_substring, expected_log, admin_user, organization, organization_admin_role
    ):
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        objects = {'organization': [{'ansible_id': organization.resource.ansible_id, 'name': organization.name}]}
        if log_level:
            with expected_log(claims_logger, log_level, log_substring):
                save_user_claims(authentication.user, objects, object_roles, [])

    def test_apply_rbac_permissions_org_duplicate_name_error(self, expected_log, admin_user, organization, organization_admin_role):
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        objects = {'organization': [{'ansible_id': str(uuid4()), 'name': organization.name}]}
        object_roles = {"Organization Admin": {'content_type': 'organization', 'objects': [0]}}
        with expected_log(claims_logger, "warning", "Got integrity error"):
            save_user_claims(authentication.user, objects, object_roles, [])

    def test_apply_rbac_permissions_removed_when_removed_from_jwt(self, admin_user, organization, organization_admin_role):
        # Make sure we have a System Auditor role
        RoleDefinition.objects.get_or_create(
            name='System Auditor',
            defaults={
                'description': 'Migrated singleton role giving read permission to everything',
                'managed': True,
            },
        )

        authentication = JWTCommonAuth()
        authentication.user = admin_user
        objects = {'organization': [{'ansible_id': organization.resource.ansible_id, 'name': organization.name}]}
        object_roles = {organization_admin_role.name: {'content_type': 'organization', 'objects': [0]}}
        global_roles = ["Platform Auditor"]

        save_user_claims(authentication.user, objects, object_roles, global_roles)

        assert RoleUserAssignment.objects.filter(user=admin_user).count() == 2

        # Test removing all roles
        save_user_claims(authentication.user, {}, {}, [])

        assert RoleUserAssignment.objects.filter(user=admin_user).count() == 0

    @pytest.mark.django_db
    def test_get_or_create_resource_invalid_content_type(self):
        assert get_or_create_resource({}, 'junk', {'ansible_id': uuid4()}) == (None, None)

    @pytest.mark.django_db
    def test_get_or_create_resource_organization(self):
        data = {'ansible_id': uuid4(), 'name': 'Test Organization'}
        assert not Organization.objects.filter(name=data['name']).exists()
        assert not Resource.objects.filter(ansible_id=data['ansible_id']).exists()
        resource, obj = get_or_create_resource(data, 'organization', data)
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
        resource, obj = get_or_create_resource(authentication.token['objects'], 'team', data)
        assert resource is not None and obj is not None
        assert Organization.objects.filter(name=org_name).exists()
        assert Resource.objects.filter(ansible_id=data['ansible_id']).exists()
        assert Team.objects.filter(name=data['name']).exists()

    @pytest.mark.parametrize(
        "cache_hit,local_match,gateway_success,expected_cache_update,expected_gateway_call,expected_rbac_call",
        [
            # Cache hit - should return early without processing
            (True, True, True, False, False, False),
            # Cache miss but local match - should update cache and return
            (False, True, True, True, False, False),
            # Cache miss and local mismatch, gateway success - should fetch and apply
            (False, False, True, True, True, True),
            # Cache miss and local mismatch, gateway failure - should not apply
            (False, False, False, False, True, False),
        ],
    )
    def test_process_rbac_permissions_cache_scenarios(
        self,
        cache_hit,
        local_match,
        gateway_success,
        expected_cache_update,
        expected_gateway_call,
        expected_rbac_call,
        admin_user,
    ):
        """Test process_rbac_permissions cache hit/miss scenarios"""

        # Setup authentication object
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        user_ansible_id = "12345678-1234-5678-9abc-123456789012"
        jwt_claims_hash = "a1b2c3d4"
        local_claims_hash = jwt_claims_hash if local_match else "e5f6g7h8"
        cached_claims_hash = jwt_claims_hash if cache_hit else "x9y8z7w6"

        authentication.token = {
            "sub": user_ansible_id,
            "claims_hash": jwt_claims_hash,
        }

        # Mock gateway response with realistic data structure matching get_user_claims format
        gateway_response = (
            {
                'claims_hash': jwt_claims_hash,  # Gateway should return the matching hash
                'objects': {
                    'organization': [
                        {'ansible_id': '11111111-1111-1111-1111-111111111111', 'name': 'Engineering Org'},
                        {'ansible_id': '22222222-2222-2222-2222-222222222222', 'name': 'DevOps Team Org'},
                    ],
                    'team': [{'ansible_id': '33333333-3333-3333-3333-333333333333', 'name': 'Backend Team', 'org': 0}],
                },
                'object_roles': {
                    'Organization Admin': {'content_type': 'organization', 'objects': [0, 1]},
                    'Team Member': {'content_type': 'team', 'objects': [0]},
                },
                'global_roles': ['Platform Auditor'],
            }
            if gateway_success
            else None
        )

        with (
            mock.patch.object(authentication.cache, 'get_cached_claims_hash') as mock_get_cache,
            mock.patch.object(authentication.cache, 'cache_claims_hash') as mock_set_cache,
            mock.patch('ansible_base.rbac.claims.get_user_claims') as mock_get_claims,
            mock.patch('ansible_base.rbac.claims.get_user_claims_hashable_form') as mock_get_hashable,
            mock.patch('ansible_base.rbac.claims.get_claims_hash') as mock_get_hash,
            mock.patch.object(authentication, '_fetch_jwt_claims_from_gateway') as mock_gateway,
            mock.patch('ansible_base.rbac.claims.save_user_claims') as mock_apply,
        ):

            # Setup mocks
            mock_get_cache.return_value = cached_claims_hash if cache_hit else None
            mock_get_claims.return_value = {}
            mock_get_hashable.return_value = {}
            mock_get_hash.return_value = local_claims_hash
            mock_gateway.return_value = gateway_response

            # Execute the method
            if not gateway_success and not cache_hit and not local_match:
                # Gateway failure case should raise AuthenticationFailed
                with pytest.raises(AuthenticationFailed, match="Unable to validate user permissions"):
                    authentication.process_rbac_permissions()
                # Early return - no further assertions needed for this case
                return
            else:
                authentication.process_rbac_permissions()

            # Verify cache lookup happened
            mock_get_cache.assert_called_once_with(user_ansible_id)

            # Verify local claims calculation - only called when cache miss occurs
            if cache_hit:
                # Cache hit - no local claims calculation needed
                mock_get_claims.assert_not_called()
                mock_get_hashable.assert_not_called()
                mock_get_hash.assert_not_called()
            else:
                # Cache miss - local claims calculation should happen
                mock_get_claims.assert_called_once_with(admin_user)
                mock_get_hashable.assert_called_once_with({})  # mock_get_claims returns {}
                mock_get_hash.assert_called_once_with({})  # mock_get_hashable returns {}

            # Verify cache update behavior
            if expected_cache_update:
                mock_set_cache.assert_called_once_with(user_ansible_id, jwt_claims_hash)
            else:
                mock_set_cache.assert_not_called()

            # Verify gateway call behavior
            if expected_gateway_call:
                mock_gateway.assert_called_once_with(user_ansible_id)
            else:
                mock_gateway.assert_not_called()

            # Verify RBAC application behavior
            if expected_rbac_call:
                mock_apply.assert_called_once_with(admin_user, gateway_response['objects'], gateway_response['object_roles'], gateway_response['global_roles'])
            else:
                mock_apply.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "is_superuser_value,should_allow",
        [
            (True, True),  # Superuser should be allowed when gateway is locked
            (False, False),  # Non-superuser should be denied when gateway is locked
        ],
    )
    def test_process_rbac_permissions_gateway_locked(self, admin_user, is_superuser_value, should_allow):
        """Test process_rbac_permissions handles GatewayLockedException based on superuser status"""
        from ansible_base.jwt_consumer.common.auth import GatewayLockedException

        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {"sub": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "claims_hash": "a1b2c3d4", "user_data": {"is_superuser": is_superuser_value}}

        with (
            mock.patch.object(authentication.cache, 'get_cached_claims_hash') as mock_get_cache,
            mock.patch.object(authentication, '_fetch_jwt_claims_from_gateway') as mock_gateway,
        ):
            # Setup mocks - cache miss to trigger gateway call
            mock_get_cache.return_value = None
            mock_gateway.side_effect = GatewayLockedException("Gateway is locked")

            if should_allow:
                # Superuser should be allowed - no exception raised
                authentication.process_rbac_permissions()
            else:
                # Non-superuser should be denied
                with pytest.raises(Exception) as exc_info:
                    authentication.process_rbac_permissions()
                assert "not a superuser and gateway is locked" in str(exc_info.value)

    @pytest.mark.django_db
    def test_process_rbac_permissions_gateway_fetch_exception(self, admin_user):
        """Test process_rbac_permissions handles generic exceptions from gateway fetch"""
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {"sub": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "claims_hash": "a1b2c3d4", "user_data": {"is_superuser": False}}

        with (
            mock.patch.object(authentication.cache, 'get_cached_claims_hash') as mock_get_cache,
            mock.patch.object(authentication, '_fetch_jwt_claims_from_gateway') as mock_gateway,
        ):
            # Setup mocks - cache miss to trigger gateway call
            mock_get_cache.return_value = None
            mock_gateway.side_effect = Exception("Network error")

            # Should raise an exception with the error details
            with pytest.raises(Exception) as exc_info:
                authentication.process_rbac_permissions()
            assert "unable to validate user permissions" in str(exc_info.value).lower()
            assert "network error" in str(exc_info.value).lower()

    @pytest.mark.django_db
    def test_process_rbac_permissions_missing_token_data(self):
        """Test process_rbac_permissions with missing required token data"""
        authentication = JWTCommonAuth()
        authentication.user = None
        authentication.token = None

        with mock.patch('ansible_base.jwt_consumer.common.auth.logger') as mock_logger:
            authentication.process_rbac_permissions()
            mock_logger.error.assert_called_with("Unable to process rbac permissions because user or token is not defined")

    @pytest.mark.django_db
    def test_process_rbac_permissions_missing_claims_hash(self, admin_user):
        """Test process_rbac_permissions with missing claims_hash in token"""
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {"sub": "f47ac10b-58cc-4372-a567-0e02b2c3d479"}  # Missing claims_hash

        with mock.patch('ansible_base.jwt_consumer.common.auth.logger') as mock_logger:
            authentication.process_rbac_permissions()
            mock_logger.error.assert_called_with("No claims_hash found in JWT token")

    @pytest.mark.django_db
    def test_process_rbac_permissions_missing_subject(self, admin_user):
        """Test process_rbac_permissions with missing subject in token"""
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {"claims_hash": "a1b2c3d4"}  # Missing sub

        with mock.patch('ansible_base.jwt_consumer.common.auth.logger') as mock_logger:
            authentication.process_rbac_permissions()
            mock_logger.error.assert_called_with("No subject (sub) found in JWT token")


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

    @pytest.mark.django_db()
    @pytest.mark.parametrize(
        "original_is_superuser, token_is_superuser, expected_is_superuser",
        [(True, False, False), (False, True, True), (True, True, True), (False, False, False)],
    )
    def test_authenticate_is_superuser(
        self, jwt_token, django_user_model, mocked_http, test_encryption_public_key, original_is_superuser, token_is_superuser, expected_is_superuser
    ):
        """
        JWT auth should retain the original is_superuser value, except when jwt token is True
        """
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            jwt_username = jwt_token.unencrypted_token['user_data']['username']
            user = django_user_model.objects.create_user(username=jwt_username, password="password", is_superuser=original_is_superuser)
            jwt_auth = JWTAuthentication()
            jwt_auth.common_auth.user = user
            jwt_auth.common_auth.token = jwt_token.unencrypted_token
            jwt_auth.common_auth.token['user_data']['is_superuser'] = token_is_superuser
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
            created_user, _ = jwt_auth.authenticate(request)
            assert created_user.is_superuser == expected_is_superuser

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

    @pytest.mark.django_db
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

    @pytest.mark.parametrize('new_user', [True, False])
    def test_correctly_authenticate_if_the_cached_key_is_invalid_but_the_new_key_is_correct(
        self, random_public_key, mocked_http, test_encryption_public_key, django_user_model, jwt_token, create_mock_method, new_user
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
                if not new_user:
                    user = django_user_model.objects.create_user(username=jwt_token.unencrypted_token['user_data']['username'], password="password")
                created_user, _ = jwt_auth.authenticate(request)
                if not new_user:
                    assert created_user == user
                else:
                    assert created_user.username == jwt_token.unencrypted_token['user_data']['username']
                    assert str(created_user.resource.ansible_id) == jwt_token.unencrypted_token['sub']

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

    def test__fetch_jwt_claims_from_gateway_success(self):
        authentication = JWTCommonAuth()
        user_ansible_id = '12345678-1234-5678-9abc-123456789012'

        with mock.patch('ansible_base.jwt_consumer.common.auth.get_resource_server_client') as mock_get_client:
            mock_client = mock.Mock()
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {'objects': {}, 'object_roles': {}, 'global_roles': []}
            mock_client._make_request.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = authentication._fetch_jwt_claims_from_gateway(user_ansible_id)

            assert result == {'objects': {}, 'object_roles': {}, 'global_roles': []}
            mock_get_client.assert_called_once_with(service_path='api/gateway/v1')
            mock_client._make_request.assert_called_once_with('GET', f'jwt_claims/{user_ansible_id}/')

    def test__fetch_jwt_claims_from_gateway_non_200(self):
        authentication = JWTCommonAuth()
        user_ansible_id = '12345678-1234-5678-9abc-123456789012'
        from ansible_base.jwt_consumer.common.auth import InvalidGatewayResponseException

        with mock.patch('ansible_base.jwt_consumer.common.auth.get_resource_server_client') as mock_get_client:
            mock_client = mock.Mock()
            mock_response = mock.Mock()
            mock_response.status_code = 404
            mock_client._make_request.return_value = mock_response
            mock_get_client.return_value = mock_client

            # Should raise InvalidGatewayResponseException for non-200/423 status codes
            with pytest.raises(InvalidGatewayResponseException) as exc_info:
                authentication._fetch_jwt_claims_from_gateway(user_ansible_id)
            assert "gateway request failed with status 404" in str(exc_info.value).lower()
            mock_get_client.assert_called_once_with(service_path='api/gateway/v1')
            mock_client._make_request.assert_called_once_with('GET', f'jwt_claims/{user_ansible_id}/')

    def test__fetch_jwt_claims_from_gateway_423_locked(self):
        authentication = JWTCommonAuth()
        user_ansible_id = '12345678-1234-5678-9abc-123456789012'
        from ansible_base.jwt_consumer.common.auth import GatewayLockedException

        with mock.patch('ansible_base.jwt_consumer.common.auth.get_resource_server_client') as mock_get_client:
            mock_client = mock.Mock()
            mock_response = mock.Mock()
            mock_response.status_code = 423
            mock_client._make_request.return_value = mock_response
            mock_get_client.return_value = mock_client

            # Should raise GatewayLockedException for 423 status
            with pytest.raises(GatewayLockedException) as exc_info:
                authentication._fetch_jwt_claims_from_gateway(user_ansible_id)
            assert "gateway is locked" in str(exc_info.value).lower()
            mock_get_client.assert_called_once_with(service_path='api/gateway/v1')
            mock_client._make_request.assert_called_once_with('GET', f'jwt_claims/{user_ansible_id}/')

    def test__fetch_jwt_claims_from_gateway_exception(self):
        authentication = JWTCommonAuth()
        user_ansible_id = '12345678-1234-5678-9abc-123456789012'

        with mock.patch('ansible_base.jwt_consumer.common.auth.get_resource_server_client', side_effect=Exception('boom')):
            # Should re-raise the exception
            with pytest.raises(Exception) as exc_info:
                authentication._fetch_jwt_claims_from_gateway(user_ansible_id)
            assert "boom" in str(exc_info.value)


class TestRbacAwareJWTAuthentication:
    @pytest.mark.django_db
    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'test_app', 'ansible_base.resource_registry', 'ansible_base.rbac'])
    def test_use_rbac_permissions_true_when_rbac_installed(self):
        """Test that use_rbac_permissions is True when ansible_base.rbac is in INSTALLED_APPS"""
        auth = RbacAwareJWTAuthentication()
        assert auth.use_rbac_permissions is True

    @pytest.mark.django_db
    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'test_app', 'ansible_base.resource_registry'])
    def test_use_rbac_permissions_false_when_rbac_not_installed(self):
        """Test that use_rbac_permissions is False when ansible_base.rbac is not in INSTALLED_APPS"""
        auth = RbacAwareJWTAuthentication()
        assert auth.use_rbac_permissions is False

    @pytest.mark.django_db
    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'test_app', 'ansible_base.resource_registry', 'ansible_base.rbac'])
    def test_process_permissions_calls_rbac_when_enabled(self):
        """Test that process_permissions calls RBAC processing when RBAC is installed"""
        with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.process_rbac_permissions') as mock_process:
            auth = RbacAwareJWTAuthentication()
            auth.process_permissions()
            mock_process.assert_called_once()

    @pytest.mark.django_db
    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'test_app', 'ansible_base.resource_registry'])
    def test_process_permissions_skips_rbac_when_disabled(self, caplog, shut_up_logging):
        """Test that process_permissions logs info message when RBAC is not installed"""
        with caplog.at_level(logging.INFO):
            auth = RbacAwareJWTAuthentication()
            auth.process_permissions()
            assert "process_permissions was not overridden for JWTAuthentication" in caplog.text
