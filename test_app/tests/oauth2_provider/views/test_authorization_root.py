from django.urls import reverse


def test_oauth2_provider_authorization_root_view(admin_api_client, unauthenticated_api_client, user_api_client):
    """
    As an admin, accessing /o/ gives an index of oauth endpoints.
    """
    url = reverse("oauth_authorization_root_view")
    for client in (admin_api_client, unauthenticated_api_client, user_api_client):
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert 'authorize' in response.data
