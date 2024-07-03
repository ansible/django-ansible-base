import re
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
def test_dupe_slug(ldap_authenticator):
    ldap_auth = Authenticator.objects.first()
    ldap_slug = ldap_auth.slug

    dupe = Authenticator()
    dupe.name = ldap_auth.name
    dupe.type = ldap_auth.type

    ldap_auth.name = "changed"
    ldap_auth.save()

    dupe.save()
    pattern = ldap_slug + '[a-z0-9_]{8}'
    assert re.match(pattern, dupe.slug) is not None
