from ansible_base.lib.utils.response import get_relative_url


def test_oauth2_provider_authorization_root_view(admin_api_client, unauthenticated_api_client, user_api_client):
    """
    As an admin, accessing /o/ gives an index of oauth endpoints.
    """
    url = get_relative_url("oauth_authorization_root_view")
    for client in (admin_api_client, unauthenticated_api_client, user_api_client):
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert 'authorize' in response.data
