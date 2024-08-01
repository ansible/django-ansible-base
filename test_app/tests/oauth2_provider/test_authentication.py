from unittest import mock

import pytest
from oauthlib.common import generate_token

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2AccessToken


@pytest.fixture
def only_oauth_scope_permission(settings):
    from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

    with mock.patch('rest_framework.views.APIView.permission_classes', [OAuth2ScopePermission]):
        yield


def test_oauth2_bearer_get_user_correct(unauthenticated_api_client, oauth2_admin_access_token):
    """
    Perform a GET with a bearer token and ensure the authed user is correct.
    """
    url = get_relative_url("user-me")
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {oauth2_admin_access_token.token}'},
    )
    assert response.status_code == 200
    assert response.data['username'] == oauth2_admin_access_token.user.username


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
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token.token if token == 'fixture' else generate_token()
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
    url = get_relative_url("animal-list")
    token = oauth2_admin_access_token.token if token == 'fixture' else generate_token()
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
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token.token if token == 'fixture' else generate_token()
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
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token.token if token == 'fixture' else generate_token()
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


def test_oauth2_bearer_no_activitystream(unauthenticated_api_client, oauth2_admin_access_token, animal):
    """
    Ensure no activitystream entries for bearer token based auth
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token.token
    existing_as_count = len(oauth2_admin_access_token.activity_stream_entries)

    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == 200
    assert response.data['name'] == animal.name

    updated_token = OAuth2AccessToken.objects.get(token=token)
    assert len(updated_token.activity_stream_entries) == existing_as_count


@pytest.mark.parametrize(
    'scope, status',
    [
        ('write', 201),
        ('read write', 201),
        ('write read', 201),
        ('read', 403),
    ],
)
@pytest.mark.django_db
def test_oauth2_scope_permission(request, admin_user, oauth2_admin_access_token, unauthenticated_api_client, scope, status, only_oauth_scope_permission):
    """
    Ensure that scopes are adhered to for PATs
    """
    oauth2_admin_access_token.scope = scope
    oauth2_admin_access_token.save()

    url = get_relative_url("animal-list")
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.post(
        url,
        data=data,
        headers={'Authorization': f'Bearer {oauth2_admin_access_token.token}'},
    )
    assert response.status_code == status, response.status_code


def test_oauth2_scope_permission_not_oauth(user, user_api_client, only_oauth_scope_permission):
    """
    Ensure that non-OAuth (but still authenticated) requests pass through.
    """

    url = get_relative_url("animal-list")
    data = {
        "name": "Fido",
        "owner": user.pk,
    }
    response = user_api_client.post(url, data=data)
    assert response.status_code == 201, response.status_code


def test_oauth2_scope_permission_not_authenticated(user, unauthenticated_api_client, only_oauth_scope_permission):
    """
    Ensure that non-authenticated are blocked.
    """

    url = get_relative_url("animal-list")
    data = {
        "name": "Fido",
        "owner": user.pk,
    }
    response = unauthenticated_api_client.post(url, data=data)
    assert response.status_code == 401, response.status_code


def test_oauth2_unsupported_media_type(user, user_api_client, only_oauth_scope_permission):
    url = get_relative_url("animal-upload")
    data = b'TESTDATA'
    response = user_api_client.post(url, data=data, content_type='application/octet-stream')
    assert response.status_code == 200, response.status_code
