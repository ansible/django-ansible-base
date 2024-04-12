from unittest import mock

import pytest

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils.user import can_user_change_password


@pytest.mark.parametrize(
    "authenticators,expected_result",
    [
        (None, False),
        ([], True),
        (["system"], False),
        (["system", "local", "ldap"], False),
        (["local"], True),
        (["ldap"], False),
        (["ldap", "saml"], False),
        (["saml", "local"], True),
        (["custom"], False),
        (["custom", "local"], True),
    ],
)
def test_can_user_change_password(
    authenticators, expected_result, system_user, random_user, local_authenticator, ldap_authenticator, custom_authenticator, saml_authenticator
):
    if authenticators is None:
        user = None
    else:
        if 'system' in authenticators:
            user = system_user
        else:
            user = random_user

        for authenticator in authenticators:
            if authenticator == 'local':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=local_authenticator)
            elif authenticator == 'ldap':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=ldap_authenticator)
            elif authenticator == 'custom':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=custom_authenticator)
            elif authenticator == 'saml':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=saml_authenticator)

    assert can_user_change_password(user) == expected_result


def test_can_user_change_password_import_error(local_authenticator, random_user):
    AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=local_authenticator)
    with mock.patch('ansible_base.authentication.utils.user.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        assert can_user_change_password(random_user) is False
