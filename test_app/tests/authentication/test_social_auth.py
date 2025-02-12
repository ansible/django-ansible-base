from unittest import mock

import pytest
from django.conf import settings
from django.test import override_settings

from ansible_base.authentication.social_auth import (
    AuthenticatorStorage,
    AuthenticatorStrategy,
    SocialAuthMixin,
    SocialAuthValidateCallbackMixin,
    create_user_claims_pipeline,
)


@mock.patch("ansible_base.authentication.social_auth.logger")
@override_settings(ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION='does.not.exist')
def test_authenticator_strategy_init_fail_to_load_function(logger):
    _ = AuthenticatorStrategy(storage=AuthenticatorStorage())
    logger.error.assert_any_call(SubstringMatcher(f"Failed to run {settings.ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION} to get additional settings"))


@mock.patch("ansible_base.authentication.social_auth.logger")
@override_settings(ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION='test_app.tests.authentication.test_social_auth.set_settings')
def test_authenticator_strategy_init_load_function(logger):
    strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
    logger.debug.assert_any_call(f"Attempting to load social settings from {settings.ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION}")
    assert strategy.settings['A_SETTING'] == "set"


def set_settings():
    return {"A_SETTING": "set"}


# borrowed from https://www.michaelpollmeier.com/python-mock-how-to-assert-a-substring-of-logger-output
class SubstringMatcher:
    def __init__(self, containing):
        self.containing = containing.lower()

    def __eq__(self, other):
        return other.lower().find(self.containing) > -1

    def __unicode__(self):
        return 'a string containing "%s"' % self.containing

    __repr__ = __unicode__


@pytest.mark.django_db
@pytest.mark.parametrize(
    "test_data,has_instance,has_slug,expected_result",
    [
        ({'foo': 'bar'}, True, True, {'foo': 'bar'}),
        ({'configuration': {'CALLBACK_URL': '/foo/bar'}}, True, True, {'configuration': {'CALLBACK_URL': '/foo/bar'}}),
        ({'configuration': {}}, True, True, {'configuration': {'CALLBACK_URL': '/foo/bar'}}),
        (
            {'type': 'foo', 'name': 'bar', 'configuration': {}},
            False,
            False,
            {'type': 'foo', 'name': 'bar', 'configuration': {'CALLBACK_URL': '/foo/bar'}, 'slug': 'generated_slug'},
        ),
    ],
)
@mock.patch("ansible_base.authentication.social_auth.get_fully_qualified_url")
@mock.patch("ansible_base.authentication.social_auth.generate_authenticator_slug", return_value="generated_slug")
def test_social_auth_validate_callback_mixin(mocked_generate_slug, mocked_reverse, test_data, has_instance, has_slug, expected_result):
    mocked_reverse.return_value = '/foo/bar'

    Serializer = mock.Mock()
    serializer = Serializer()
    serializer.instance = None
    serializer.context = {'request': None}
    if has_instance:
        SerializerInstance = mock.Mock()
        serializer.instance = SerializerInstance()
        if has_slug:
            serializer.instace.slug = 'slug'

    mixin = SocialAuthValidateCallbackMixin()
    res = mixin.validate(serializer, test_data)
    assert res == expected_result

    # should generate a slug if the serializer has no instance
    if not has_instance:
        assert mocked_generate_slug.called

    # should always call reverse if no callback url
    if has_instance and 'configuration' in test_data and not test_data.get('configuration', {}).get('CALLBACK_URL'):
        assert mocked_reverse.called


@pytest.mark.parametrize(
    "groups_claim,returned_groups,expected_groups",
    [
        (None, ["mygroup"], ["mygroup"]),
        ("groups", ["mygroup"], ["mygroup"]),
        (None, None, []),
        ("groups", None, []),
    ],
)
@mock.patch("ansible_base.authentication.utils.claims.update_user_claims")
def test_create_user_claims_pipeline(mock_update_user_claims, groups_claim, returned_groups, expected_groups):
    '''
    We are testing to see if extracting groups from a claim is working correctly
    '''

    class MockBackend(SocialAuthMixin):
        database_instance = None

        def __init__(self, groups_claim=None):
            if groups_claim is not None:
                self.groups_claim = groups_claim

        def get_user_groups(self, extra_groups=[]):
            return extra_groups

    backend = MockBackend(groups_claim=groups_claim)

    rData = {}
    if returned_groups is not None:
        rData[backend.groups_claim] = returned_groups

    user = {
        'auth_time': "2024-11-07T05:19:08.224936Z",
        'id_token': "asdf",
        'refresh_token': None,
        'id': "ccd2cf13-d927-41ad-cd8c-adb18b2e5f78",
        'access_token': "asdf",
        'token_type': "Bearer",
    }

    create_user_claims_pipeline(backend=backend, response=rData, user=user)

    assert mock_update_user_claims.called
    call_args = mock_update_user_claims.call_args

    assert call_args == ((user, None, expected_groups),)
