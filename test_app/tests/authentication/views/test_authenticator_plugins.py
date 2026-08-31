import pytest
from django.test import override_settings

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class, get_authenticator_plugins
from ansible_base.authentication.views.authenticator_plugins import _inject_validation_patterns
from ansible_base.lib.utils.response import get_relative_url


def test_plugin_authenticator_view(admin_api_client):
    """
    Test the authenticator plugin view. It should show all available plugins
    (which exist on the system as python files, not database entries).
    """
    url = get_relative_url("authenticator_plugin-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'authenticators' in response.data

    auth_types = [x['type'] for x in response.data['authenticators']]
    assert 'ansible_base.authentication.authenticator_plugins.ldap' in auth_types
    assert 'ansible_base.authentication.authenticator_plugins.local' in auth_types


def test_plugin_authenticator_view_import_error(admin_api_client, shut_up_logging, settings):
    """
    Test that import errors are returned as expected.
    """

    fixture_module = "test_app.tests.fixtures.authenticator_plugins"
    settings.ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = [
        "ansible_base.authentication.authenticator_plugins",
        fixture_module,
    ]

    get_authenticator_plugins.cache_clear()

    url = get_relative_url("authenticator_plugin-view")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert 'authenticators' in response.data

    auth_types = [x['type'] for x in response.data['authenticators']]
    assert 'ansible_base.authentication.authenticator_plugins.ldap' in auth_types
    assert 'ansible_base.authentication.authenticator_plugins.local' in auth_types
    assert 'broken' not in auth_types

    assert 'errors' in response.data
    assert f'The specified authenticator type {fixture_module}.broken could not be loaded' in response.data['errors']
    assert f'The specified authenticator type {fixture_module}.really_broken could not be loaded' in response.data['errors']


def test_plugin_authenticator_plugin_from_custom_module(admin_user, unauthenticated_api_client, shut_up_logging, settings, custom_authenticator):
    """
    Test that we can auth with a fully custom authenticator plugin.
    """

    fixture_module = "test_app.tests.fixtures.authenticator_plugins"
    settings.ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = [
        "ansible_base.authentication.authenticator_plugins",
        fixture_module,
    ]

    url = get_relative_url("authenticator-detail", kwargs={'pk': custom_authenticator.pk})

    client = unauthenticated_api_client
    client.login(username=admin_user.username, password="wrongpw")
    response = client.get(url)
    assert response.status_code == 401

    client.login(username=admin_user.username, password="hello123")
    response = client.get(url)
    assert response.status_code == 200
    assert response.data['type'] == f'{fixture_module}.custom'


# ---------------------------------------------------------------------------
# _inject_validation_patterns — pattern injection for plugin config schemas
# ---------------------------------------------------------------------------


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
def test_inject_validation_patterns_adds_patterns_to_charfields():
    klass = get_authenticator_class('ansible_base.authentication.authenticator_plugins.github')
    config = klass.configuration_class()
    schema = config.get_configuration_schema()
    _inject_validation_patterns(schema, config, klass.configuration_encrypted_fields)
    schema_by_name = {entry['name']: entry for entry in schema}

    assert 'pattern' in schema_by_name['KEY']
    assert 'patternDescription' in schema_by_name['KEY']
    assert schema_by_name['KEY']['flags'] == 'i'

    assert 'pattern' not in schema_by_name['SECRET']
    assert 'patternDescription' not in schema_by_name['SECRET']


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
def test_inject_validation_patterns_noop_when_disabled():
    klass = get_authenticator_class('ansible_base.authentication.authenticator_plugins.github')
    config = klass.configuration_class()
    schema = config.get_configuration_schema()
    _inject_validation_patterns(schema, config, klass.configuration_encrypted_fields)
    for entry in schema:
        assert 'pattern' not in entry, f"Field {entry['name']} should not have pattern when feature is disabled"


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
def test_inject_validation_patterns_skips_non_charfields():
    klass = get_authenticator_class('ansible_base.authentication.authenticator_plugins.ldap')
    config = klass.configuration_class()
    schema = config.get_configuration_schema()
    _inject_validation_patterns(schema, config, ['BIND_PASSWORD'])
    schema_by_name = {entry['name']: entry for entry in schema}

    assert 'pattern' not in schema_by_name['START_TLS']
    assert 'pattern' in schema_by_name['BIND_DN']
    assert 'pattern' not in schema_by_name['BIND_PASSWORD']


@pytest.mark.django_db
@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
def test_authenticator_plugins_endpoint_includes_patterns(admin_api_client):
    url = get_relative_url("authenticator_plugin-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200

    github_plugin = next(a for a in response.data['authenticators'] if a['type'] == 'ansible_base.authentication.authenticator_plugins.github')
    schema_by_name = {e['name']: e for e in github_plugin['configuration_schema']}
    assert 'pattern' in schema_by_name['KEY']
    assert 'pattern' not in schema_by_name['SECRET']
