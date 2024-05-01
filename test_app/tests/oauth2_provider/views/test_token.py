import base64

import pytest
from django.urls import reverse
from django.utils.http import urlencode

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.oauth2_provider.models import OAuth2AccessToken


@pytest.mark.django_db
@pytest.mark.parametrize(
    'client_fixture, user_fixture',
    [
        pytest.param('user_api_client', 'user', id='user'),
        pytest.param('admin_api_client', 'admin_user', id='admin'),
    ],
)
def test_oauth2_provider_list_user_tokens(request, client_fixture, user_fixture):
    client = request.getfixturevalue(client_fixture)
    user = request.getfixturevalue(user_fixture)
    url = reverse('token-list')
    response = client.post(url, data={'scope': 'read'})
    assert response.status_code == 201
    assert response.data['scope'] == 'read'
    assert response.data['user'] == user.pk

    get_response = client.get(url)
    assert get_response.status_code == 200
    assert len(get_response.data['results']) == 1


@pytest.mark.django_db
@pytest.mark.parametrize('allow_oauth, status', [(True, 201), (False, 403)])
def test_oauth2_token_creation_disabled_for_external_accounts(
    oauth2_application_password,
    user,
    ldap_authenticator,
    local_authenticator,
    settings,
    unauthenticated_api_client,
    allow_oauth,
    status,
):
    """
    If ALLOW_OAUTH2_FOR_EXTERNAL_USERS is enabled, users associated with an external authentication provider
    can create OAuth2 tokens. Otherwise, they cannot.
    """
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    app = oauth2_application_password[0]
    secret = oauth2_application_password[1]
    url = reverse('token')
    settings.ALLOW_OAUTH2_FOR_EXTERNAL_USERS = allow_oauth
    data = {
        'grant_type': 'password',
        'username': 'user',
        'password': 'password',
        'scope': 'read',
    }
    resp = unauthenticated_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )

    assert resp.status_code == status
    if allow_oauth:
        assert OAuth2AccessToken.objects.count() == 1
    else:
        assert 'OAuth2 Tokens cannot be created by users associated with an external authentication provider' in resp.content.decode()
        assert OAuth2AccessToken.objects.count() == 0


@pytest.mark.django_db
def test_oauth2_existing_token_enabled_for_external_accounts(
    oauth2_application_password, user, unauthenticated_api_client, settings, ldap_authenticator, local_authenticator
):
    """
    If a token already exists but then ALLOW_OAUTH2_FOR_EXTERNAL_USERS becomes False
    the token should still be usable.
    """
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    app = oauth2_application_password[0]
    secret = oauth2_application_password[1]
    url = reverse('token')
    settings.ALLOW_OAUTH2_FOR_EXTERNAL_USERS = True
    data = {
        'grant_type': 'password',
        'username': 'user',
        'password': 'password',
        'scope': 'read',
    }
    resp = unauthenticated_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )
    assert resp.status_code == 201
    token = resp.json()['access_token']
    assert OAuth2AccessToken.objects.count() == 1

    for val in (True, False):
        settings.ALLOW_OAUTH2_FOR_EXTERNAL_USERS = val
        url = reverse('user-me')
        resp = unauthenticated_api_client.get(
            url,
            headers={'Authorization': f'Bearer {token}'},
        )
        assert resp.json()['username'] == user.username


@pytest.mark.django_db
def test_oauth2_pat_creation(oauth2_application_password, user, unauthenticated_api_client):
    app = oauth2_application_password[0]
    secret = oauth2_application_password[1]
    url = reverse('token')
    data = {
        "grant_type": "password",
        "username": "user",
        "password": "password",
        "scope": "read",
    }
    resp = unauthenticated_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )

    assert resp.status_code == 201, resp.content
    resp_json = resp.json()
    assert 'access_token' in resp_json
    assert len(resp_json['access_token']) > 0
    assert 'scope' in resp_json
    assert resp_json['scope'] == 'read'
    assert 'refresh_token' in resp_json


@pytest.mark.django_db
def test_oauth2_pat_creation_no_default_scope(oauth2_application, admin_api_client):
    """
    Tests that the default scope is overriden
    """
    url = reverse('token-list')
    response = admin_api_client.post(
        url,
        {
            'description': 'test token',
            'scope': 'read',
            'application': oauth2_application[0].pk,
        },
    )
    assert response.data['scope'] == 'read'


@pytest.mark.django_db
def test_oauth2_pat_creation_no_scope(oauth2_application, admin_api_client):
    """
    Tests that the default scope is as expected
    """
    url = reverse('token-list')
    response = admin_api_client.post(
        url,
        {
            'description': 'test token',
            'application': oauth2_application[0].pk,
        },
    )
    assert response.data['scope'] == 'write'


def test_oauth2_pat_list_for_user(oauth2_user_pat, oauth2_user_pat_1, user, admin_api_client):
    """
    Tests that we can list a user's PATs via API.
    """
    url = reverse('user-personal-tokens-list', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 2


def test_oauth2_pat_list_for_invalid_user(oauth2_user_pat, oauth2_user_pat_1, user, admin_api_client):
    """
    Ensure we don't fatal if we give a bad user PK.

    We return an empty list.
    """
    url = reverse('user-personal-tokens-list', kwargs={"pk": 1000})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['results'] == []


def test_oauth2_pat_list_is_user_related_field(user, admin_api_client):
    """
    Ensure 'personal_tokens' shows up in the user's related fields.
    """
    url = reverse('user-detail', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'personal_tokens' in response.data['related']
    assert response.data['delated']['personal_tokens'] == reverse('user-personal-tokens-list', kwargs={"pk": user.pk})
