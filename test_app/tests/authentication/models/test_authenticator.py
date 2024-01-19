from unittest import mock

import pytest

from ansible_base.authentication.models import Authenticator


@pytest.mark.django_db
def test_authenticator_from_db(ldap_authenticator):
    ldap_auth = Authenticator.objects.first()
    # Validate that we got the proper password when loading the object the first time
    assert ldap_auth.configuration.get('BIND_PASSWORD', None) == 'securepassword'
    with mock.patch('ansible_base.authentication.models.authenticator.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        ldap_auth = Authenticator.objects.first()
        assert ldap_auth.configuration.get('BIND_PASSWORD', None) != 'securepassword'
