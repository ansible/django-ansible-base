import pytest
from django.urls import reverse
from oauthlib.common import generate_token


def test_oauth2_bearer_get_user_correct(unauthenticated_api_client, oauth2_admin_access_token):
    """
    Perform a GET with a bearer token and ensure the authed user is correct.
    """
    url = reverse("user-me")
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {oauth2_admin_access_token}'},
    )
    assert response.status_code == 200
    assert response.data['username'] == 'admin'


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_get(unauthenticated_api_client, oauth2_admin_access_token, animal, token, expected):
    """
    GET an animal with a bearer token.
    """
    url = reverse("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token if token == 'fixture' else generate_token()
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == animal.name


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 201),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_post(unauthenticated_api_client, oauth2_admin_access_token, admin_user, token, expected):
    """
    POST an animal with a bearer token.
    """
    url = reverse("animal-list")
    token = oauth2_admin_access_token if token == 'fixture' else generate_token()
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.post(
        url,
        data=data,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == 'Fido'


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_patch(unauthenticated_api_client, oauth2_admin_access_token, animal, admin_user, token, expected):
    """
    PATCH an animal with a bearer token.
    """
    url = reverse("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token if token == 'fixture' else generate_token()
    data = {
        "name": "Fido",
    }
    response = unauthenticated_api_client.patch(
        url,
        data=data,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == 'Fido'


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_put(unauthenticated_api_client, oauth2_admin_access_token, animal, admin_user, token, expected):
    """
    PUT an animal with a bearer token.
    """
    url = reverse("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token if token == 'fixture' else generate_token()
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.put(
        url,
        data=data,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == 'Fido'
