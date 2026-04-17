import pytest
from django.conf import settings
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
def test_oauth2_provider_openid_configuration_requires_oidc_enabled(client):
    """
    As an anonymous user, accessing /o/.well-known/openid-configuration/ should fail
    when OIDC_ENABLED is not set in OAUTH2_PROVIDER settings.
    """
    with override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, 'OIDC_ENABLED': False}):
        url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
        response = client.get(url)
        assert response.status_code != 200, f"Expected non-200 when OIDC is disabled, got {response.status_code}"
