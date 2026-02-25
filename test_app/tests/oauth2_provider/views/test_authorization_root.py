import pytest

from ansible_base.lib.testing.util import feature_flag_enabled
from ansible_base.lib.utils.response import get_relative_url


def test_oauth2_provider_authorization_root_view(admin_api_client, unauthenticated_api_client, user_api_client):
    """
    As an admin, accessing /o/ gives an index of oauth endpoints.
    """
    url = get_relative_url("oauth2_provider:oauth_authorization_root_view")
    for client in (admin_api_client, unauthenticated_api_client, user_api_client):
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert 'authorize' in response.data


@pytest.mark.django_db
def test_oidc_endpoints_shown_when_flag_enabled(admin_api_client):
    """
    OIDC endpoints are shown when feature flag is enabled.
    """
    with feature_flag_enabled("FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED"):
        url = get_relative_url("oauth2_provider:oauth_authorization_root_view")
        response = admin_api_client.get(url)
        assert 'oidc-connect-discovery-info' in response.data
        assert 'jwks-info' in response.data
