import pytest

from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.oauth2_provider.utils import is_external_account


@pytest.mark.parametrize("link_local, link_ldap, expected", [(False, False, False), (True, False, False), (False, True, True), (True, True, True)])
def test_oauth2_provider_is_external_account_with_user(user, local_authenticator, ldap_authenticator, link_local, link_ldap, expected):
    if link_local:
        # Link the user to the local authenticator
        local_au = AuthenticatorUser(provider=local_authenticator, user=user)
        local_au.save()
    if link_ldap:
        # Link the user to the ldap authenticator
        ldap_au = AuthenticatorUser(provider=ldap_authenticator, user=user)
        ldap_au.save()

    assert is_external_account(user) is expected


def test_oauth2_provider_is_external_account_import_error(user, local_authenticator):
    au = AuthenticatorUser(provider=local_authenticator, user=user)
    au.save()
    local_authenticator.type = "test_app.tests.fixtures.authenticator_plugins.broken"
    # Avoid save() which would raise an ImportError
    Authenticator.objects.bulk_update([local_authenticator], ['type'])
    assert is_external_account(user)
