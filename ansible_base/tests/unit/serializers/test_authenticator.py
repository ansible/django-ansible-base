import pytest

from ansible_base.serializers import AuthenticatorSerializer


@pytest.mark.django_db
def test_removed_authenticator_plugin(ldap_authenticator, shut_up_logging):
    serializer = AuthenticatorSerializer()
    item = serializer.to_representation(ldap_authenticator)
    assert 'error' not in item
    assert 'configuration' in item
    assert item['configuration'] != {}

    # Change the type of the LDAP authenticator
    ldap_authenticator.type = 'junk'
    item = serializer.to_representation(ldap_authenticator)
    assert 'error' in item
    assert 'configuration' in item
    assert item['configuration'] == {}
