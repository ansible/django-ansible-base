from unittest import mock

import pytest

import ansible_base.authentication.backend as backend
from ansible_base.authentication.models import Authenticator


@pytest.mark.django_db
def test_authenticator_backends_import_error(ldap_authenticator):
    # Load one item
    assert len(backend.get_authentication_backends("fake date")) == 1

    # Change the get_authenticator_plugin to fail, this will cause the backend to not be able to load
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        # Force the cache to get evicted by updating an authenticator.
        assert len(backend.get_authentication_backends("fake date2")) == 0


@pytest.mark.django_db
def test_authenticator_backends_cache(ldap_authenticator):
    last_modified = Authenticator.objects.values("modified_on").order_by("-modified_on").first()["modified_on"]

    # Load one item
    assert len(backend.get_authentication_backends(last_modified)) == 1

    # verify that the cache is evicted when an authenticator is updated.
    ldap_authenticator.name = "new_name"
    ldap_authenticator.save()

    last_modified = Authenticator.objects.values("modified_on").order_by("-modified_on").first()["modified_on"]
    authenticator = backend.get_authentication_backends(last_modified)[ldap_authenticator.pk]
    assert authenticator.database_instance.name == "new_name"

    # verify that the cache is not updated if the last_modified date is the same
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=OSError("Test Exception")):
        # If the function reruns, get_authenticator_plugin will throw an exception here
        authenticator = backend.get_authentication_backends(last_modified)[ldap_authenticator.pk]
        assert authenticator.database_instance.name == "new_name"
