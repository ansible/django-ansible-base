import pytest
from django.test import override_settings

from ansible_base.lib.testing.util import feature_flag_disabled, feature_flag_enabled
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_valid_issuer_url(client):
    """
    As an anonymous user, accessing /o/.well-known/openid-configuration/ should include
    an issuer URL that ends with /o
    """
    with feature_flag_enabled('FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED'):
        with override_settings(OAUTH2_PROVIDER={'OIDC_ENABLED': True}):
            url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
            response = client.get(url)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"
            response_json = response.json()
            assert response_json['issuer'].endswith(
                '/o'
            ), "issuer in discovery metadata is expected to end with /o and match the authorization root view, otherwise discovery will fail!"


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_404_without_feature_flag(client):
    """
    As an anonymous user, accessing /o/.well-known/openid-configuration/ should fail
    with 404 if the feature is not enabled
    """
    with feature_flag_disabled('FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED'):
        url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
        response = client.get(url)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
