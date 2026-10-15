import base64
import hashlib
import json
import time
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils.http import urlencode

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.hashing import hash_string
from ansible_base.lib.utils.response import get_relative_url
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
    url = get_relative_url('oauth2_provider:token')
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
    url = get_relative_url('oauth2_provider:token')
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
        url = get_relative_url('user-me')
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
    url = get_relative_url('token-list')
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
    url = get_relative_url('oauth2_provider:token')
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
    url = get_relative_url('token-list')
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
    url = get_relative_url('token-list')
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
    url = get_relative_url('user-personal-tokens-list', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 2


def test_oauth2_pat_list_for_invalid_user(oauth2_user_pat, oauth2_user_pat_1, user, admin_api_client):
    """
    Ensure we don't fatal if we give a bad user PK.

    We return an empty list.
    """
    url = get_relative_url('user-personal-tokens-list', kwargs={"pk": 1000})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['results'] == []


def test_oauth2_pat_list_is_user_related_field(user, admin_api_client):
    """
    Ensure 'personal_tokens' shows up in the user's related fields.
    """
    url = get_relative_url('user-detail', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'personal_tokens' in response.data['related']
    assert response.data['related']['personal_tokens'] == get_relative_url('user-personal-tokens-list', kwargs={"pk": user.pk})


def test_oauth2_application_token_summary_fields(admin_api_client, oauth2_admin_access_token, oauth2_application):
    url = get_relative_url('application-detail', kwargs={'pk': oauth2_application[0].pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['summary_fields']['tokens']['count'] == 1
    assert response.data['summary_fields']['tokens']['results'][0] == {'id': oauth2_admin_access_token[0].pk, 'scope': 'write', 'token': ENCRYPTED_STRING}


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

    url = get_relative_url('user-authorized-tokens-list', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 2


def test_oauth2_authorized_list_for_invalid_user(oauth2_user_pat, oauth2_user_pat_1, user, admin_api_client):
    """
    Ensure we don't fatal if we give a bad user PK.

    We return an empty list.
    """
    url = get_relative_url('user-authorized-tokens-list', kwargs={"pk": 1000})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['results'] == []


def test_oauth2_authorized_list_is_user_related_field(user, admin_api_client):
    """
    Ensure 'authorized_tokens' shows up in the user's related fields.
    """
    url = get_relative_url('user-detail', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'authorized_tokens' in response.data['related']
    assert response.data['related']['authorized_tokens'] == get_relative_url('user-authorized-tokens-list', kwargs={"pk": user.pk})


@pytest.mark.django_db
def test_oauth2_token_create(oauth2_application, admin_api_client, admin_user):
    oauth2_application = oauth2_application[0]
    url = get_relative_url('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application.pk})
    assert response.status_code == 201
    assert 'modified' in response.data and response.data['modified'] is not None
    assert 'updated' not in response.data
    hashed_token = hash_string(response.data['token'], hasher=hashlib.sha256, algo="sha256")
    token = OAuth2AccessToken.objects.get(token=hashed_token)
    hashed_refresh_token = hash_string(response.data['refresh_token'], hasher=hashlib.sha256, algo="sha256")
    refresh_token = OAuth2RefreshToken.objects.get(token=hashed_refresh_token)
    assert token.application == oauth2_application
    assert refresh_token.application == oauth2_application
    assert token.user == admin_user
    assert refresh_token.user == admin_user
    assert refresh_token.access_token == token
    assert token.scope == 'read'

    url = get_relative_url('application-access_tokens-list', kwargs={'pk': oauth2_application.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == token.pk

    url = get_relative_url('application-detail', kwargs={'pk': oauth2_application.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['summary_fields']['tokens']['count'] == 1
    assert response.data['summary_fields']['tokens']['results'][0] == {'id': token.pk, 'scope': token.scope, 'token': ENCRYPTED_STRING}

    url = get_relative_url('token-list')
    response = admin_api_client.post(url, {'scope': 'write', 'application': oauth2_application.pk})
    assert response.status_code == 201
    assert response.data['refresh_token']

    url = get_relative_url('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application.pk, 'user': admin_user.pk})
    assert response.status_code == 201
    assert response.data['refresh_token']

    url = get_relative_url('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application.pk})
    assert response.status_code == 201
    assert response.data['refresh_token']


@pytest.mark.django_db
def test_oauth2_token_update(oauth2_admin_access_token, admin_api_client):
    assert oauth2_admin_access_token[0].scope == 'write'
    url = get_relative_url('token-detail', kwargs={'pk': oauth2_admin_access_token[0].pk})
    response = admin_api_client.patch(url, {'scope': 'read'})
    assert response.status_code == 200
    oauth2_admin_access_token[0].refresh_from_db()
    assert oauth2_admin_access_token[0].scope == 'read'


@pytest.mark.django_db
def test_oauth2_token_delete(oauth2_admin_access_token, admin_api_client):
    url = get_relative_url('token-detail', kwargs={'pk': oauth2_admin_access_token[0].pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert OAuth2AccessToken.objects.count() == 0
    assert OAuth2RefreshToken.objects.count() == 1

    url = get_relative_url('application-access_tokens-list', kwargs={'pk': oauth2_admin_access_token[0].application.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['count'] == 0

    url = get_relative_url('application-detail', kwargs={'pk': oauth2_admin_access_token[0].application.pk})
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
    refresh_token = oauth2_admin_access_token[2]
    refresh_token_obj = oauth2_admin_access_token[0].refresh_token

    url = get_relative_url('oauth2_provider:token')
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }
    resp = unauthenticated_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )
    assert resp.status_code == 201
    assert OAuth2RefreshToken.objects.filter(token=refresh_token_obj.token).exists()
    original_refresh_token = OAuth2RefreshToken.objects.get(token=refresh_token_obj.token)
    assert oauth2_admin_access_token not in OAuth2AccessToken.objects.all()
    assert OAuth2AccessToken.objects.count() == 1

    # the same RefreshToken remains but is marked revoked
    assert OAuth2RefreshToken.objects.count() == 2
    assert original_refresh_token.revoked

    json_resp = json.loads(resp.content)
    new_token = json_resp['access_token']
    new_token_hashed = hash_string(new_token, hasher=hashlib.sha256, algo="sha256")
    new_refresh_token = json_resp['refresh_token']
    new_refresh_token_hashed = hash_string(new_refresh_token, hasher=hashlib.sha256, algo="sha256")

    assert OAuth2AccessToken.objects.filter(token=new_token_hashed).count() == 1
    # checks that RefreshTokens are rotated (new RefreshToken issued)
    assert OAuth2RefreshToken.objects.filter(token=new_refresh_token_hashed).count() == 1
    new_refresh_obj = OAuth2RefreshToken.objects.get(token=new_refresh_token_hashed)
    assert not new_refresh_obj.revoked


@pytest.mark.django_db
def test_oauth2_refresh_token_expiration_is_respected(oauth2_application, oauth2_admin_access_token, admin_api_client, settings):
    """
    Test that a refresh token that has expired cannot be used to refresh an access token.
    """
    app = oauth2_application[0]
    secret = oauth2_application[1]
    refresh_token = oauth2_admin_access_token[2]
    refresh_token_obj = oauth2_admin_access_token[0].refresh_token

    settings.OAUTH2_PROVIDER['REFRESH_TOKEN_EXPIRE_SECONDS'] = 1
    settings.OAUTH2_PROVIDER['ACCESS_TOKEN_EXPIRE_SECONDS'] = 1
    settings.OAUTH2_PROVIDER['AUTHORIZATION_CODE_EXPIRE_SECONDS'] = 1
    time.sleep(1)

    url = get_relative_url('oauth2_provider:token')
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }
    response = admin_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )
    assert response.status_code == 403
    assert b'The refresh token has expired.' in response.content
    assert OAuth2RefreshToken.objects.filter(token=refresh_token_obj.token).exists()
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
    url = get_relative_url('user-tokens-list', kwargs={"pk": user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 6


@pytest.mark.parametrize(
    'given,error',
    [
        ('read write', None),
        ('read', None),
        ('write', None),
        ('openid', None),
        ('roles', None),
        ('openid roles', None),
        ('read write openid roles', None),
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

    url = get_relative_url("token-list")

    # Create PAT
    data = {
        'description': 'new PAT',
        'scope': given,
    }
    response = user_api_client.post(url, data=data)
    assert response.status_code == 400 if error else 201
    if error:
        assert error in str(response.data['scope'][0])


def _assert_ttl_delta(token_pk, expected_seconds, tolerance=10):
    """Assert that (expires - created) of the token with `token_pk` is within `tolerance` seconds of `expected_seconds`."""
    token = OAuth2AccessToken.objects.get(pk=token_pk)
    delta = (token.expires - token.created).total_seconds()
    assert abs(delta - expected_seconds) <= tolerance, f"Expected delta ~{expected_seconds}s, got {delta}s"


@pytest.mark.django_db
def test_oauth2_token_ttl_omitted_uses_platform_default(user_api_client, settings):
    """
    Regression: omitting `ttl` preserves the existing behavior, the access token
    lifetime is `ACCESS_TOKEN_EXPIRE_SECONDS`.
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-list')
    response = user_api_client.post(url, {'scope': 'read'})
    assert response.status_code == 201, response.data
    _assert_ttl_delta(response.data['id'], 3600)


@pytest.mark.django_db
def test_oauth2_token_ttl_shorten(user_api_client, settings):
    """
    A `ttl` below the platform default shortens the access token lifetime.
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-list')
    response = user_api_client.post(url, {'scope': 'read', 'ttl': 1800})
    assert response.status_code == 201, response.data
    # `ttl` is write-only and must never be echoed in the response
    assert 'ttl' not in response.data
    _assert_ttl_delta(response.data['id'], 1800)


@pytest.mark.django_db
def test_oauth2_token_ttl_equal_to_platform_default(user_api_client, settings):
    """
    A `ttl` equal to the platform default is accepted.
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-list')
    response = user_api_client.post(url, {'scope': 'read', 'ttl': 3600})
    assert response.status_code == 201, response.data
    _assert_ttl_delta(response.data['id'], 3600)


@pytest.mark.django_db
@pytest.mark.parametrize('client_fixture', ['user_api_client', 'admin_api_client'])
def test_oauth2_token_ttl_above_platform_default(request, client_fixture, settings):
    """
    A `ttl` above the platform default is rejected for both regular users and admins.
    """
    client = request.getfixturevalue(client_fixture)
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-list')
    response = client.post(url, {'scope': 'read', 'ttl': 7200})
    assert response.status_code == 400, response.data
    assert 'must not exceed the platform default of 3600' in str(response.data['ttl'][0])


@pytest.mark.django_db
def test_oauth2_token_ttl_negative(user_api_client, settings):
    """
    `ttl` must be a non-negative integer (min_value=0).
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-list')
    response = user_api_client.post(url, {'scope': 'read', 'ttl': -5})
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_oauth2_token_ttl_zero_uses_platform_default(user_api_client, settings):
    """
    `ttl=0` is accepted and means use the platform default's TTL.
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-list')
    response = user_api_client.post(url, {'scope': 'read', 'ttl': 0})
    assert response.status_code == 201, response.data
    _assert_ttl_delta(response.data['id'], 3600)


@pytest.mark.django_db
def test_oauth2_token_ttl_with_zero_platform_default(user_api_client, settings):
    """
    Misconfiguration: when `ACCESS_TOKEN_EXPIRE_SECONDS` is 0, any positive `ttl` is
    accepted and the token is valid (not already expired).
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 0,
    }
    url = get_relative_url('token-list')
    response = user_api_client.post(url, {'scope': 'read', 'ttl': 3600})
    assert response.status_code == 201, response.data
    _assert_ttl_delta(response.data['id'], 3600)


@pytest.mark.django_db
def test_oauth2_token_ttl_zero_with_zero_platform_default(user_api_client, settings):
    """
    `ttl=0` means "use the platform default": with a zero platform default the
    default path applies, so the token is created already expired, same as omitting
    teh `ttl` (the zero setting is a pre-existing misconfiguration
    that the codebase already warns about).
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 0,
    }
    url = get_relative_url('token-list')
    response = user_api_client.post(url, {'scope': 'read', 'ttl': 0})
    assert response.status_code == 201, response.data
    _assert_ttl_delta(response.data['id'], 0)


@pytest.mark.django_db
def test_oauth2_token_ttl_app_token(oauth2_application, admin_api_client, settings):
    """
    The same `ttl` rules apply to application tokens.
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application[0].pk, 'ttl': 1800})
    assert response.status_code == 201, response.data
    _assert_ttl_delta(response.data['id'], 1800)
    # A refresh token is still created for app tokens
    assert OAuth2RefreshToken.objects.count() == 1


@pytest.mark.django_db
def test_oauth2_token_ttl_does_not_affect_refresh_token(oauth2_application, admin_api_client, settings):
    """
    `ttl` only governs the access token; the refresh token is still governed by
    `REFRESH_TOKEN_EXPIRE_SECONDS`.
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
        'REFRESH_TOKEN_EXPIRE_SECONDS': 7200,
    }
    url = get_relative_url('token-list')
    response = admin_api_client.post(url, {'scope': 'read', 'application': oauth2_application[0].pk, 'ttl': 1800})
    assert response.status_code == 201, response.data
    access_token = OAuth2AccessToken.objects.get(pk=response.data['id'])
    refresh_token = OAuth2RefreshToken.objects.get(access_token=access_token)
    # The access token lifetime is governed by `ttl`
    _assert_ttl_delta(access_token.pk, 1800)
    # The refresh token is not stamped with the `ttl`; its effective expiry is
    # `created + REFRESH_TOKEN_EXPIRE_SECONDS` (see TokenView.create_token_response),
    # i.e. governed by the platform setting, not by `ttl`
    effective_refresh_expiry = refresh_token.created + timedelta(seconds=7200)
    assert effective_refresh_expiry > access_token.expires


@pytest.mark.django_db
def test_oauth2_grant_flow_unaffected_by_ttl(oauth2_application_password, user, unauthenticated_api_client, settings):
    """
    The `/o/token/` grant flow is unaffected by `ttl`; `expires_in` still equals
    `ACCESS_TOKEN_EXPIRE_SECONDS`.

    Note: django-oauth-toolkit caches its settings and the view's `OAuthLibCore`
    (which bakes `token_expires_in` in at construction), so `override_settings`
    (which triggers the `setting_changed` signal) plus
    `ALWAYS_RELOAD_OAUTHLIB_CORE` are used instead of mutating the dict.
    """
    with override_settings(
        OAUTH2_PROVIDER={
            **settings.OAUTH2_PROVIDER,
            'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
            'ALWAYS_RELOAD_OAUTHLIB_CORE': True,
        }
    ):
        app = oauth2_application_password[0]
        secret = oauth2_application_password[1]
        url = get_relative_url('oauth2_provider:token')
        data = {
            'grant_type': 'password',
            'username': user.username,
            'password': 'password',
            'scope': 'read',
        }
        resp = unauthenticated_api_client.post(
            url,
            data=urlencode(data),
            content_type='application/x-www-form-urlencoded',
            headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
        )
        assert resp.status_code == 201, resp.content
        assert resp.json()['expires_in'] == 3600


@pytest.mark.django_db
def test_oauth2_token_ttl_rejected_on_update(oauth2_admin_access_token, admin_api_client, admin_user, settings):
    """
    `ttl` can only be set at token creation; PATCH/PUT with `ttl` is rejected.
    """
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    }
    url = get_relative_url('token-detail', kwargs={'pk': oauth2_admin_access_token[0].pk})
    response = admin_api_client.patch(url, {'ttl': 1800})
    assert response.status_code == 400, response.data
    assert 'can only be set at token creation' in str(response.data['ttl'][0])

    response = admin_api_client.put(url, {'user': admin_user.pk, 'ttl': 1800})
    assert response.status_code == 400, response.data
    assert 'can only be set at token creation' in str(response.data['ttl'][0])
