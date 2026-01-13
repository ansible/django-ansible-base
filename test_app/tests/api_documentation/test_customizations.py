"""
Unit tests for api_documentation customizations.

Tests the OAuth2 security scheme customization that allows the
LoggedOAuth2Authentication to leverage the OAuth2 customization settings.
These change allow the OAuth2Authentication securityScheme to be listed as
'oauth2' instead of 'apiKey'.
"""

from unittest.mock import MagicMock


def test_oauth2_scheme_type_is_oauth2_not_apikey():
    """Test OAuth2Scheme returns type 'oauth2' instead of 'apiKey'.

    drf-spectacular auto-detects OAuth2Authentication as 'apiKey',
    but the method overrides it to the correct definition.
    """
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

    # Intentionally access _registry to verify OAuth2Scheme is registered with expected attributes
    oauth2_schemes = [
        ext for ext in OpenApiAuthenticationExtension._registry if hasattr(ext, 'target_class') and ext.target_class == LoggedOAuth2Authentication
    ]
    assert len(oauth2_schemes) >= 1, "OAuth2_Authentication should be registered"

    # Get the first matching scheme
    oauth2_scheme_cls = oauth2_schemes[0]
    assert oauth2_scheme_cls.name == 'OAuth2_Authentication'

    # Instantiate and get security definition
    oauth2_scheme = oauth2_scheme_cls(target=LoggedOAuth2Authentication)
    # Use MagicMock for auto_schema parameter
    security_def = oauth2_scheme.get_security_definition(auto_schema=MagicMock())

    # CRITICAL: Must be 'oauth2', not 'apiKey'
    assert security_def['type'] == 'oauth2', "OAuth2 security scheme must have type 'oauth2', not 'apiKey'"
    assert 'flows' in security_def


def test_oauth2_scheme_includes_configured_flows():
    """Test get_security_definition includes flows from SPECTACULAR_SETTINGS."""
    from django.conf import settings
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

    # Intentionally access _registry to verify OAuth2Scheme is registered with expected attributes
    oauth2_schemes = [
        ext for ext in OpenApiAuthenticationExtension._registry if hasattr(ext, 'target_class') and ext.target_class == LoggedOAuth2Authentication
    ]
    oauth2_scheme = oauth2_schemes[0](target=LoggedOAuth2Authentication)
    security_def = oauth2_scheme.get_security_definition(auto_schema=MagicMock())

    flows = security_def['flows']
    configured_flows = settings.SPECTACULAR_SETTINGS['OAUTH2_FLOWS']

    for flow_type in configured_flows:
        assert flow_type in flows
        assert 'scopes' in flows[flow_type]

        # Verify flow-specific URLs
        if flow_type in ('implicit', 'authorizationCode'):
            assert 'authorizationUrl' in flows[flow_type]
        if flow_type in ('password', 'clientCredentials', 'authorizationCode'):
            assert 'tokenUrl' in flows[flow_type]
