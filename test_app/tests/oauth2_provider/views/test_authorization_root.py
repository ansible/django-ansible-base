from django.urls import reverse


def test_oauth2_provider_authorization_root_view_as_admin(admin_api_client):
    """
    As an admin, accessing /o/ gives an index of oauth endpoints.
    """
    url = reverse("oauth_authorization_root_view")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert 'authorize' in response.data


def test_oauth2_provider_authorization_root_view_anon(client):
    """
    As an anonymous user, accessing /o/ gives an index of oauth endpoints.
    """
    url = reverse("oauth_authorization_root_view")
    response = client.get(url)

    assert response.status_code == 200
    assert 'authorize' in response.data
