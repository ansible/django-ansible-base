import importlib
from unittest import mock
from unittest.mock import MagicMock

import pytest

from ansible_base.authentication.authenticator_plugins import ldap

"""
This module is separated from the rest of test_ldap.py because it reloads the module
which will replace the auth utils module with newly loaded classes.
So it gives best isolation to keep this in a module that does not have
other imports from the same module, which can leave stale references.
"""


@pytest.mark.django_db
@pytest.mark.parametrize(
    "username",
    [
        ("Timmy"),
        ("TIMMY"),
        ("TiMmY"),
    ],
)
def test_get_or_build_user(username, ldap_authenticator):
    with mock.patch(
        'ansible_base.authentication.utils.authentication.get_or_create_authenticator_user', return_value=(None, None, None)
    ) as get_or_create_authenticator_user:
        importlib.reload(ldap)
        plugin = ldap.AuthenticatorPlugin(database_instance=ldap_authenticator)
        ldap_object = MagicMock()
        plugin.get_or_build_user(username, ldap_object)
        assert get_or_create_authenticator_user.called
        assert username.lower() in get_or_create_authenticator_user.call_args.kwargs['uid']
        assert username not in get_or_create_authenticator_user.call_args.kwargs['uid']


@pytest.mark.django_db
def test_get_or_build_user_uses_first_ldap_email(ldap_authenticator):
    with mock.patch(
        'ansible_base.authentication.utils.authentication.get_or_create_authenticator_user', return_value=(None, None, None)
    ) as get_or_create_authenticator_user:
        importlib.reload(ldap)
        plugin = ldap.AuthenticatorPlugin(database_instance=ldap_authenticator)
        ldap_object = MagicMock()
        ldap_object.settings.USER_ATTR_MAP = {'email': 'mail'}
        ldap_object.attrs.data.get.return_value = 'first@example.com'

        plugin.get_or_build_user('Timmy', ldap_object)

        assert get_or_create_authenticator_user.call_args.kwargs['email'] == 'first@example.com'
        ldap_object.attrs.data.get.assert_called_once_with('mail', '')
