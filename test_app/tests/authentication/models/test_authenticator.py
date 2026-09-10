import logging
from unittest import mock
from unittest.mock import patch

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


@pytest.mark.django_db
def test_dupe_slug(ldap_authenticator):
    ldap_slug = ldap_authenticator.slug

    dupe = Authenticator()
    dupe.name = ldap_authenticator.name
    dupe.type = ldap_authenticator.type

    ldap_authenticator.name = "changed"
    ldap_authenticator.save()

    dupe.save()
    assert dupe.slug != ldap_slug, "authenticator slugs should be unique"


@pytest.mark.django_db
def test_authenticator_from_db_invalid_token_logs_and_reraises(ldap_authenticator, caplog):
    """Authenticator.from_db() must log CRITICAL and re-raise InvalidToken.

    Simulates a SECRET_KEY change making encrypted authenticator configuration
    fields (e.g. LDAP BIND_PASSWORD) undecryptable -- part of AAP-76852.
    """
    from cryptography.fernet import InvalidToken

    with patch("ansible_base.lib.utils.encryption.ansible_encryption.decrypt_string", side_effect=InvalidToken):
        with caplog.at_level(logging.CRITICAL, logger="ansible_base.authentication.models.authenticator"):
            with pytest.raises(InvalidToken):
                Authenticator.objects.get(pk=ldap_authenticator.pk)

    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert critical_records, "Expected at least one CRITICAL log record"
    assert any("SECRET_KEY" in r.message for r in critical_records), "Expected CRITICAL log to mention SECRET_KEY"
    assert any(ldap_authenticator.name in r.message for r in critical_records), "Expected CRITICAL log to include the authenticator name"
