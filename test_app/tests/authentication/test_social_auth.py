from unittest import mock

from django.conf import settings
from django.test import override_settings

from ansible_base.authentication.social_auth import AuthenticatorStorage, AuthenticatorStrategy


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
