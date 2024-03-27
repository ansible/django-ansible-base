#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from unittest import mock

import pytest
from django.conf import settings
from django.test import override_settings

from ansible_base.authentication.social_auth import AuthenticatorStorage, AuthenticatorStrategy, SocialAuthValidateCallbackMixin


@mock.patch("ansible_base.authentication.social_auth.logger")
@override_settings(ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION='does.not.exist')
def test_authenticator_strategy_init_fail_to_load_function(logger):
    _ = AuthenticatorStrategy(storage=AuthenticatorStorage())
    logger.error.assert_any_call(SubstringMatcher(f"Failed to run {settings.ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION} to get additional settings"))


@mock.patch("ansible_base.authentication.social_auth.logger")
@override_settings(ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION='test_app.tests.authentication.test_social_auth.set_settings')
def test_authenticator_strategy_init_load_function(logger):
    strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
    logger.info.assert_any_call(f"Attempting to load social settings from {settings.ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION}")
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


@pytest.mark.parametrize(
    "test_data,has_instance,has_slug,expected_result",
    [
        ({'foo': 'bar'}, True, True, {'foo': 'bar'}),
        ({'configuration': {'CALLBACK_URL': '/foo/bar'}}, True, True, {'configuration': {'CALLBACK_URL': '/foo/bar'}}),
        ({'configuration': {}}, True, True, {'configuration': {'CALLBACK_URL': '/foo/bar'}}),
        ({'type': 'foo', 'name': 'bar', 'configuration': {}}, False, False, {'type': 'foo', 'name': 'bar', 'configuration': {'CALLBACK_URL': '/foo/bar'}}),
    ],
)
@mock.patch("ansible_base.authentication.social_auth.reverse")
@mock.patch("ansible_base.authentication.social_auth.generate_authenticator_slug")
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
