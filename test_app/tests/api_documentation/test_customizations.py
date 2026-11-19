"""
Unit tests for api_documentation authentication schema customizations.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.parametrize(
    ('flow_type', 'expected_urls'),
    [
        ('implicit', {'authorizationUrl': 'https://example.test/o/authorize/'}),
        (
            'authorizationCode',
            {
                'authorizationUrl': 'https://example.test/o/authorize/',
                'tokenUrl': 'https://example.test/o/token/',
            },
        ),
        ('password', {'tokenUrl': 'https://example.test/o/token/'}),
        ('clientCredentials', {'tokenUrl': 'https://example.test/o/token/'}),
        ('custom', {}),
    ],
)
def test_oauth2_flow_definition_includes_urls_for_its_flow_type(flow_type, expected_urls):
    from ansible_base.api_documentation.customizations import _oauth2_flow_definition

    spectacular_settings = SimpleNamespace(
        OAUTH2_SCOPES={'read': 'Read access'},
        OAUTH2_AUTHORIZATION_URL='https://example.test/o/authorize/',
        OAUTH2_TOKEN_URL='https://example.test/o/token/',
        OAUTH2_REFRESH_URL='https://example.test/o/token/refresh/',
    )

    assert _oauth2_flow_definition(flow_type, spectacular_settings) == {
        **expected_urls,
        'refreshUrl': 'https://example.test/o/token/refresh/',
        'scopes': {'read': 'Read access'},
    }


def test_oauth2_flows_builds_a_definition_for_every_configured_flow():
    from ansible_base.api_documentation.customizations import _oauth2_flows

    spectacular_settings = SimpleNamespace(
        OAUTH2_FLOWS=['implicit', 'password'],
        OAUTH2_SCOPES=None,
        OAUTH2_AUTHORIZATION_URL='https://example.test/o/authorize/',
        OAUTH2_TOKEN_URL='https://example.test/o/token/',
        OAUTH2_REFRESH_URL=None,
    )

    assert _oauth2_flows(spectacular_settings) == {
        'implicit': {
            'authorizationUrl': 'https://example.test/o/authorize/',
            'scopes': {},
        },
        'password': {
            'tokenUrl': 'https://example.test/o/token/',
            'scopes': {},
        },
    }


def test_dab_lib_doc_excludes_clean_text_mixin():
    from rest_framework import serializers

    from ansible_base.api_documentation.customizations import get_dab_lib_doc_excludes
    from ansible_base.lib.serializers.mixins import CleanTextMixin

    excludes = get_dab_lib_doc_excludes()

    assert CleanTextMixin in excludes
    assert serializers.ModelSerializer in excludes


def test_bearer_authentication_schema_includes_generic_bearer_and_local_oauth2():
    """A unified dispatcher advertises external Bearer and local OAuth2 as alternatives."""
    from django.conf import settings
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    from ansible_base.authentication.bearer_authentication import BearerAuthentication

    scheme = OpenApiAuthenticationExtension.get_match(BearerAuthentication())
    security_definitions = scheme.get_security_definition(auto_schema=MagicMock())

    assert scheme.name == ['BearerAuthentication', 'OAuth2_Authentication']
    assert security_definitions[0] == {'type': 'http', 'scheme': 'bearer'}
    assert security_definitions[1]['type'] == 'oauth2'
    assert scheme.get_security_requirement(auto_schema=MagicMock()) == [
        {'BearerAuthentication': []},
        {'OAuth2_Authentication': []},
    ]

    flows = security_definitions[1]['flows']
    configured_flows = settings.SPECTACULAR_SETTINGS['OAUTH2_FLOWS']

    for flow_type in configured_flows:
        assert flow_type in flows
        assert 'scopes' in flows[flow_type]

        # Verify flow-specific URLs
        if flow_type in ('implicit', 'authorizationCode'):
            assert 'authorizationUrl' in flows[flow_type]
        if flow_type in ('password', 'clientCredentials', 'authorizationCode'):
            assert 'tokenUrl' in flows[flow_type]


def test_oauth2_only_schema_targets_the_local_oauth2_authenticator():
    """OAuth2-only deployments retain their local OAuth2 OpenAPI description."""
    from django.conf import settings
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    from ansible_base.api_documentation.customizations import apply_oauth2_customizations
    from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

    installed_apps = [app for app in settings.INSTALLED_APPS if app != 'ansible_base.authentication']
    registered_extensions = set(OpenApiAuthenticationExtension._registry)
    with patch.object(settings, 'INSTALLED_APPS', installed_apps):
        apply_oauth2_customizations()
    (scheme,) = set(OpenApiAuthenticationExtension._registry) - registered_extensions

    assert scheme.target_class == LoggedOAuth2Authentication
    assert scheme.name == ['OAuth2_Authentication']
    definitions = scheme(target=LoggedOAuth2Authentication()).get_security_definition(auto_schema=MagicMock())
    assert definitions[0]['type'] == 'oauth2'


def test_oauth2_customizations_without_authentication_does_not_import_bearer_authentication():
    """OAuth2-only deployments must not load the optional authentication app."""
    from django.conf import settings

    from ansible_base.api_documentation.customizations import apply_oauth2_customizations

    installed_apps = [app for app in settings.INSTALLED_APPS if app != 'ansible_base.authentication']
    original_import = __import__

    def import_without_bearer_authentication(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'ansible_base.authentication.bearer_authentication':
            raise RuntimeError('BearerAuthentication must not be imported when the authentication app is absent')
        return original_import(name, globals, locals, fromlist, level)

    with (
        patch.object(settings, 'INSTALLED_APPS', installed_apps),
        patch('builtins.__import__', side_effect=import_without_bearer_authentication),
    ):
        apply_oauth2_customizations()


def test_oauth2_customizations_skips_registration_without_drf_spectacular():
    """OpenAPI support remains optional when drf-spectacular is unavailable."""
    from ansible_base.api_documentation.customizations import apply_oauth2_customizations

    original_import = __import__

    def import_without_drf_spectacular(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'drf_spectacular.extensions':
            raise ImportError('drf-spectacular is not installed')
        return original_import(name, globals, locals, fromlist, level)

    with patch('builtins.__import__', side_effect=import_without_drf_spectacular):
        apply_oauth2_customizations()


def test_authentication_only_schema_is_generic_bearer():
    """External authenticator plugins have no local OAuth2 flow to describe."""
    from django.conf import settings
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    from ansible_base.api_documentation.customizations import apply_oauth2_customizations
    from ansible_base.authentication.bearer_authentication import BearerAuthentication

    installed_apps = [app for app in settings.INSTALLED_APPS if app != 'ansible_base.oauth2_provider']
    registered_extensions = set(OpenApiAuthenticationExtension._registry)
    with patch.object(settings, 'INSTALLED_APPS', installed_apps):
        apply_oauth2_customizations()
    (scheme,) = set(OpenApiAuthenticationExtension._registry) - registered_extensions

    assert scheme.target_class == BearerAuthentication
    assert scheme.name == ['BearerAuthentication']
    assert scheme(target=BearerAuthentication()).get_security_definition(auto_schema=MagicMock()) == [{'type': 'http', 'scheme': 'bearer'}]
    assert scheme(target=BearerAuthentication()).get_security_requirement(auto_schema=MagicMock()) == {'BearerAuthentication': []}


def test_oauth2_schema_includes_a_configured_refresh_url():
    """The OAuth2 schema passes drf-spectacular's refresh URL through to every flow."""
    from django.conf import settings
    from drf_spectacular.extensions import OpenApiAuthenticationExtension
    from drf_spectacular.settings import spectacular_settings

    from ansible_base.api_documentation.customizations import apply_oauth2_customizations
    from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

    installed_apps = [app for app in settings.INSTALLED_APPS if app != 'ansible_base.authentication']
    registered_extensions = set(OpenApiAuthenticationExtension._registry)
    refresh_url = 'https://example.test/o/token/refresh/'
    with (
        patch.object(settings, 'INSTALLED_APPS', installed_apps),
        patch.object(spectacular_settings, 'OAUTH2_REFRESH_URL', refresh_url),
    ):
        apply_oauth2_customizations()
        (scheme,) = set(OpenApiAuthenticationExtension._registry) - registered_extensions
        definitions = scheme(target=LoggedOAuth2Authentication()).get_security_definition(auto_schema=MagicMock())

    assert all(flow['refreshUrl'] == refresh_url for flow in definitions[0]['flows'].values())


def test_no_authentication_apps_registers_no_bearer_schema():
    """Deployments without either authentication application need no Bearer schema."""
    from django.conf import settings
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    from ansible_base.api_documentation.customizations import apply_oauth2_customizations

    installed_apps = [app for app in settings.INSTALLED_APPS if app not in {'ansible_base.authentication', 'ansible_base.oauth2_provider'}]
    registered_extensions = len(OpenApiAuthenticationExtension._registry)
    with patch.object(settings, 'INSTALLED_APPS', installed_apps):
        apply_oauth2_customizations()

    assert len(OpenApiAuthenticationExtension._registry) == registered_extensions


def test_api_documentation_ready_registers_oauth2_schema_without_authentication_app():
    from django.conf import settings

    from ansible_base import api_documentation
    from ansible_base.api_documentation.apps import ApiDocumentationConfig

    installed_apps = [app for app in settings.INSTALLED_APPS if app != 'ansible_base.authentication']
    with (
        patch.object(settings, 'INSTALLED_APPS', installed_apps),
        patch('ansible_base.api_documentation.apps.apply_authentication_customizations') as apply_authentication,
        patch('ansible_base.api_documentation.apps.apply_oauth2_customizations') as apply_oauth2,
    ):
        ApiDocumentationConfig('ansible_base.api_documentation', api_documentation).ready()

    apply_authentication.assert_not_called()
    apply_oauth2.assert_called_once_with()
