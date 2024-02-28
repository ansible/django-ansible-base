from django.urls import reverse


def test_oauth2_provider_authorization_root_view(admin_api_client):
    url = reverse("oauth_authorization_root_view")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert 'authorize' in response.data
