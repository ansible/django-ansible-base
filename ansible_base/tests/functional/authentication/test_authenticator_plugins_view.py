from django.urls import reverse


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


def test_plugin_authenticator_view_import_error(admin_api_client, shut_up_logging, settings):
    """
    Test that import errors are returned as expected.
    """

    fixture_module = "ansible_base.tests.fixtures.authenticator_plugins"
    settings.ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = [
        "ansible_base.authenticator_plugins",
        fixture_module,
    ]

    url = reverse("authenticator_plugin-view")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert 'authenticators' in response.data

    auth_types = [x['type'] for x in response.data['authenticators']]
    assert 'ansible_base.authenticator_plugins.ldap' in auth_types
    assert 'ansible_base.authenticator_plugins.local' in auth_types
    assert 'broken' not in auth_types

    assert 'errors' in response.data
    assert f'The specified authenticator type {fixture_module}.broken could not be loaded' in response.data['errors']
    assert f'The specified authenticator type {fixture_module}.really_broken could not be loaded' in response.data['errors']


def test_plugin_authenticator_plugin_from_custom_module(admin_user, unauthenticated_api_client, shut_up_logging, settings, custom_authenticator):
    """
    Test that we can auth with a fully custom authenticator plugin.
    """

    fixture_module = "ansible_base.tests.fixtures.authenticator_plugins"
    settings.ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = [
        "ansible_base.authenticator_plugins",
        fixture_module,
    ]

    url = reverse("authenticator-detail", kwargs={'pk': custom_authenticator.pk})

    client = unauthenticated_api_client
    client.login(username=admin_user.username, password="wrongpw")
    response = client.get(url)
    assert response.status_code == 403

    client.login(username=admin_user.username, password="hello123")
    response = client.get(url)
    assert response.status_code == 200
    assert response.data['type'] == f'{fixture_module}.custom'
