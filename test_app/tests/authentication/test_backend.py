from unittest import mock

import pytest

import ansible_base.authentication.backend as backend


@pytest.mark.django_db
def test_authenticator_backends_type_change(ldap_authenticator):
    base_auth = backend.AnsibleBaseAuth()
    # Load one item
    base_auth.authenticate(None)
    assert len(backend.authentication_backends) == 1

    # Change the type of the authenticator in the in-memory cache (this would normally never happen)
    for key in backend.authentication_backends:
        print(backend.authentication_backends[key])
        setattr(backend.authentication_backends[key], 'type', 'junk')
    # Change the get_authenticator_plugin to fail, this will cause the backend to not be able to load
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        # This call should attempt to load the value out of the DB as LDAP but the get_authenticator_plugin
        #   will fail to load its type so we should end up deleting the cached authenticator
        base_auth.authenticate(None)
        assert len(backend.authentication_backends) == 0

    # Reset the backends
    backend.authentication_backends = {}

    # Change the get_authenticator_plugin to fail, this will cause the backend to not be able to load
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        base_auth.authenticate(None)
        assert len(backend.authentication_backends) == 0
