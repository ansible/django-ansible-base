from unittest.mock import patch

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_valid_issuer_url(client):
    """
    As an anonymous user, accessing /o/.well-known/openid-configuration/ should include
    an issuer URL that ends with /o
    """
    with override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, 'OIDC_ENABLED': True}):
        url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
        response = client.get(url)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        response_json = response.json()
        assert response_json['issuer'].endswith(
            '/o'
        ), "issuer in discovery metadata is expected to end with /o and match the authorization root view, otherwise discovery will fail!"


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_revocation_endpoint(client):
    """
    The OIDC discovery document should include a revocation_endpoint
    pointing to /o/revoke_token/.
    """
    with override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, 'OIDC_ENABLED': True}):
        url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
        response = client.get(url)
        assert response.status_code == 200
        response_json = response.json()
        assert 'revocation_endpoint' in response_json, "revocation_endpoint missing from OIDC discovery document"
        assert response_json['revocation_endpoint'].endswith('/o/revoke_token/')


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_code_challenge_methods(client):
    """
    The OIDC discovery document should include code_challenge_methods_supported
    advertising S256 and plain (RFC 7636).
    """
    with override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, 'OIDC_ENABLED': True}):
        url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
        response = client.get(url)
        assert response.status_code == 200
        response_json = response.json()
        assert 'code_challenge_methods_supported' in response_json, "code_challenge_methods_supported missing from OIDC discovery document"
        methods = response_json['code_challenge_methods_supported']
        assert 'S256' in methods
        assert 'plain' in methods


@pytest.mark.django_db
def test_well_known_catch_all_returns_404(client):
    """
    Unhandled /.well-known/ paths should return 404, not a login page.
    """
    response = client.get("/.well-known/something-unknown")
    assert response.status_code == 404
    assert response["Content-Type"] == "application/json"
    assert response.json() == {"error": "not_found"}


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_requires_oidc_enabled(client):
    """
    As an anonymous user, accessing /o/.well-known/openid-configuration/ should fail
    when OIDC_ENABLED is not set in OAUTH2_PROVIDER settings.
    """
    with override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, 'OIDC_ENABLED': False}):
        url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
        response = client.get(url)
        assert response.status_code != 200, f"Expected non-200 when OIDC is disabled, got {response.status_code}"


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_non_200_response_returned_unchanged(client):
    """
    When the parent ConnectDiscoveryInfoView returns a non-200 response,
    DiscoveryInfoView should return it unchanged without attempting
    to parse or modify the response body.
    """
    error_response = HttpResponse("Service Unavailable", status=503)
    with override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, 'OIDC_ENABLED': True}):
        with patch('oauth2_provider.views.oidc.ConnectDiscoveryInfoView.get', return_value=error_response):
            url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
            response = client.get(url)
            assert response.status_code == 503
            assert 'revocation_endpoint' not in response.content.decode()
