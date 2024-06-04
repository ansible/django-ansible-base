import base64
import json
import time

import pytest
from django.urls import reverse
from django.utils.http import urlencode

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken


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
@pytest.mark.parametrize(
    'client_fixture, user_fixture',
    [
        pytest.param('user_api_client', 'user', id='user'),
        pytest.param('admin_api_client', 'admin_user', id='admin'),
    ],
)
def test_oauth2_pat_create_and_list(request, client_fixture, user_fixture):
    """
    A user can create and list personal access tokens.
    """
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
    assert response.data['related']['personal_tokens'] == reverse('user-personal-tokens-list', kwargs={"pk": user.pk})


def test_oauth2_application_token_summary_fields(admin_api_client, oauth2_admin_access_token, oauth2_application):
    url = reverse('application-detail', kwargs={'pk': oauth2_application[0].pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['summary_fields']['tokens']['count'] == 1
    assert response.data['summary_fields']['tokens']['results'][0] == {'id': oauth2_admin_access_token.pk, 'scope': 'write', 'token': ENCRYPTED_STRING}


@pytest.mark.django_db
def test_oauth2_authorized_list_for_user(oauth2_application, oauth2_user_pat, oauth2_user_pat_1, user, admin_api_client):
    """
    Tests that we can list a user's authorized tokens via API.
    """
    # Turn the PATs into authorized tokens by attaching an application
    oauth2_application = oauth2_application[0]
    oauth2_user_pat.application = oauth2_application
    oauth2_user_pat.save()
    oauth2_user_pat_1.application = oauth2_application
    oauth2_user_pat_1.save()

    url = reverse('user-authorized-tokens-list', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 2


def test_oauth2_authorized_list_for_invalid_user(oauth2_user_pat, oauth2_user_pat_1, user, admin_api_client):
    """
    Ensure we don't fatal if we give a bad user PK.

    We return an empty list.
    """
    url = reverse('user-authorized-tokens-list', kwargs={"pk": 1000})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['results'] == []


def test_oauth2_authorized_list_is_user_related_field(user, admin_api_client):
    """
    Ensure 'authorized_tokens' shows up in the user's related fields.
    """
    url = reverse('user-detail', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'authorized_tokens' in response.data['related']
    assert response.data['related']['authorized_tokens'] == reverse('user-authorized-tokens-list', kwargs={"pk": user.pk})


@pytest.mark.django_db
def test_oauth2_token_createn(oauth2_application, admin_api_client, admin_user):
    oauth2_application = oauth2_application[0]
    url = reverse('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application.pk})
    assert response.status_code == 201
    assert 'modified' in response.data and response.data['modified'] is not None
    assert 'updated' not in response.data
    token = OAuth2AccessToken.objects.get(token=response.data['token'])
    refresh_token = OAuth2RefreshToken.objects.get(token=response.data['refresh_token'])
    assert token.application == oauth2_application
    assert refresh_token.application == oauth2_application
    assert token.user == admin_user
    assert refresh_token.user == admin_user
    assert refresh_token.access_token == token
    assert token.scope == 'read'

    url = reverse('application-access_tokens-list', kwargs={'pk': oauth2_application.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == token.pk

    url = reverse('application-detail', kwargs={'pk': oauth2_application.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['summary_fields']['tokens']['count'] == 1
    assert response.data['summary_fields']['tokens']['results'][0] == {'id': token.pk, 'scope': token.scope, 'token': ENCRYPTED_STRING}

    url = reverse('token-list')
    response = admin_api_client.post(url, {'scope': 'write', 'application': oauth2_application.pk})
    assert response.status_code == 201
    assert response.data['refresh_token']

    url = reverse('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application.pk, 'user': admin_user.pk})
    assert response.status_code == 201
    assert response.data['refresh_token']

    url = reverse('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application.pk})
    assert response.status_code == 201
    assert response.data['refresh_token']


@pytest.mark.django_db
def test_oauth2_token_update(oauth2_admin_access_token, admin_api_client):
    assert oauth2_admin_access_token.scope == 'write'
    url = reverse('token-detail', kwargs={'pk': oauth2_admin_access_token.pk})
    response = admin_api_client.patch(url, {'scope': 'read'})
    assert response.status_code == 200
    oauth2_admin_access_token.refresh_from_db()
    assert oauth2_admin_access_token.scope == 'read'


@pytest.mark.django_db
def test_oauth2_token_delete(oauth2_admin_access_token, admin_api_client):
    url = reverse('token-detail', kwargs={'pk': oauth2_admin_access_token.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert OAuth2AccessToken.objects.count() == 0
    assert OAuth2RefreshToken.objects.count() == 1

    url = reverse('application-access_tokens-list', kwargs={'pk': oauth2_admin_access_token.application.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['count'] == 0

    url = reverse('application-detail', kwargs={'pk': oauth2_admin_access_token.application.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['summary_fields']['tokens']['count'] == 0


@pytest.mark.django_db
def test_oauth2_refresh_access_token(oauth2_application, oauth2_admin_access_token, unauthenticated_api_client):
    """
    Test that we can refresh an access token.
    """
    app = oauth2_application[0]
    secret = oauth2_application[1]
    refresh_token = oauth2_admin_access_token.refresh_token

    url = reverse('token')
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token.token,
    }
    resp = unauthenticated_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )
    assert resp.status_code == 201
    assert OAuth2RefreshToken.objects.filter(token=refresh_token).exists()
    original_refresh_token = OAuth2RefreshToken.objects.get(token=refresh_token)
    assert oauth2_admin_access_token not in OAuth2AccessToken.objects.all()
    assert OAuth2AccessToken.objects.count() == 1

    # the same RefreshToken remains but is marked revoked
    assert OAuth2RefreshToken.objects.count() == 2
    assert original_refresh_token.revoked

    json_resp = json.loads(resp.content)
    new_token = json_resp['access_token']
    new_refresh_token = json_resp['refresh_token']

    assert OAuth2AccessToken.objects.filter(token=new_token).count() == 1
    # checks that RefreshTokens are rotated (new RefreshToken issued)
    assert OAuth2RefreshToken.objects.filter(token=new_refresh_token).count() == 1
    new_refresh_obj = OAuth2RefreshToken.objects.get(token=new_refresh_token)
    assert not new_refresh_obj.revoked


@pytest.mark.django_db
def test_oauth2_refresh_token_expiration_is_respected(oauth2_application, oauth2_admin_access_token, admin_api_client, settings):
    """
    Test that a refresh token that has expired cannot be used to refresh an access token.
    """
    app = oauth2_application[0]
    secret = oauth2_application[1]
    refresh_token = oauth2_admin_access_token.refresh_token

    settings.OAUTH2_PROVIDER['REFRESH_TOKEN_EXPIRE_SECONDS'] = 1
    settings.OAUTH2_PROVIDER['ACCESS_TOKEN_EXPIRE_SECONDS'] = 1
    settings.OAUTH2_PROVIDER['AUTHORIZATION_CODE_EXPIRE_SECONDS'] = 1
    time.sleep(1)

    url = reverse('token')
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token.token,
    }
    response = admin_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )
    assert response.status_code == 403
    assert b'The refresh token has expired.' in response.content
    assert OAuth2RefreshToken.objects.filter(token=refresh_token).exists()
    assert OAuth2AccessToken.objects.count() == 1
    assert OAuth2RefreshToken.objects.count() == 1


def test_oauth2_tokens_list_for_user(
    oauth2_user_pat,
    oauth2_user_pat_1,
    oauth2_user_application_token,
    oauth2_user_application_token_1,
    oauth2_user_application_token_2,
    oauth2_user_application_token_3,
    user,
    admin_api_client,
):
    """
    Tests that we can list a user's tokens via user endpoint.
    """
    url = reverse('user-tokens-list', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 6


@pytest.mark.parametrize(
    'given,error',
    [
        ('read write', None),
        ('read', None),
        ('write', None),
        ('read write foo', 'Invalid scope: foo'),
        ('foo', 'Invalid scope: foo'),
        ('', None),  # default scope is 'write'
    ],
)
@pytest.mark.django_db
def test_oauth2_token_scope_validator(user_api_client, given, error):
    """
    Ensure that the scope validator works as expected.
    """

    url = reverse("token-list")

    # Create PAT
    data = {
        'description': 'new PAT',
        'scope': given,
    }
    response = user_api_client.post(url, data=data)
    assert response.status_code == 400 if error else 201
    if error:
        assert error in str(response.data['scope'][0])
