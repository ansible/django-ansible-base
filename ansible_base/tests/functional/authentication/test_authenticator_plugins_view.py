import sys

from django.urls import reverse
from pyfakefs.fake_filesystem_unittest import Patcher


def test_plugin_authenticator_view(admin_api_client):
    """
    Test the authenticator plugin view. It should show all available plugins
    (which exist on the system as python files, not database entries).
    """
    url = reverse("authenticator_plugin-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'authenticators' in response.data

    auth_types = [x['type'] for x in response.data['authenticators']]
    assert 'ansible_base.authenticator_plugins.ldap' in auth_types
    assert 'ansible_base.authenticator_plugins.local' in auth_types


def test_plugin_authenticator_view_import_error(admin_api_client, shut_up_logging):
    """
    Test that import errors are returned as expected.
    """

    # We use pyfakefs here, copy in the real directory, and then create a fake broken file.
    # We *avoid* the 'fs' fixture because it *breaks DRF in weird ways*.
    url = reverse("authenticator_plugin-view")

    with Patcher() as patcher:
        patcher.fs.add_real_directory(sys.modules['ansible_base.authenticator_plugins'].__path__[0])
        patcher.fs.create_file(sys.modules['ansible_base.authenticator_plugins'].__path__[0] + '/broken.py', contents='invalid')
        patcher.fs.create_file(sys.modules['ansible_base.authenticator_plugins'].__path__[0] + '/really_broken.py', contents='invalid')
        response = admin_api_client.get(url)

    assert response.status_code == 200
    assert 'authenticators' in response.data

    auth_types = [x['type'] for x in response.data['authenticators']]
    assert 'ansible_base.authenticator_plugins.ldap' in auth_types
    assert 'ansible_base.authenticator_plugins.local' in auth_types
    assert 'broken' not in auth_types

    assert 'errors' in response.data
    assert 'The specified authenticator type ansible_base.authenticator_plugins.broken could not be loaded' in response.data['errors']
    assert 'The specified authenticator type ansible_base.authenticator_plugins.really_broken could not be loaded' in response.data['errors']
