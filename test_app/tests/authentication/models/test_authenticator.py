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


@pytest.mark.django_db
def test_authenticator_order_on_create_update():
    """
    ensures that authenticator order = max(current order) + 1 for newly created authenticators
    and that order is generated correctly for new authenticators when there is an update in orders
    """
    auth_type = "ansible_base.authentication.authenticator_plugins.local"
    auth1 = Authenticator.objects.create(name='Authenticator 1', type=auth_type, order=11)
    auth2 = Authenticator.objects.create(name='Authenticator 2', type=auth_type)
    assert auth2.order == auth1.order + 1

    # update order of auth2
    auth2.order = 10
    auth2.save()

    auth3 = Authenticator.objects.create(name='Authenticator 3', type=auth_type)
    assert auth3.order == 12
