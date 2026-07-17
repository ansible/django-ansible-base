import pytest
from django.conf import settings
from django.test import override_settings
from django.utils.http import urlencode

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2Application


@pytest.fixture
def oauth2_app_pkce_required(randname):
    app = OAuth2Application(
        name=randname("PKCE Required App"),
        redirect_uris="https://example.com/callback",
        authorization_grant_type="authorization-code",
        client_type="confidential",
        pkce_required=True,
    )
    secret = app.client_secret
    app.save()
    return (app, secret)


@pytest.fixture
def oauth2_app_pkce_not_required(randname):
    app = OAuth2Application(
        name=randname("PKCE Not Required App"),
        redirect_uris="https://example.com/callback",
        authorization_grant_type="authorization-code",
        client_type="confidential",
        pkce_required=False,
    )
    secret = app.client_secret
    app.save()
    return (app, secret)


def test_oauth2_provider_authorize_view_as_admin(admin_api_client):
    """
    As an admin, accessing /o/authorize/ without client_id parameter should return a 400 error.
    """
    url = get_relative_url("oauth2_provider:authorize")
    response = admin_api_client.get(url)

    assert response.status_code == 400
    assert 'Missing client_id parameter.' in str(response.content)


def test_oauth2_provider_authorize_view_anon(client, settings):
    """
    As an anonymous user, accessing /o/authorize/ should redirect to the login page.
    """
    url = get_relative_url("oauth2_provider:authorize")
    response = client.get(url)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)


def test_oauth2_provider_authorize_view_flow(user_api_client, oauth2_application):
    """
    As a user, I should be able to complete the authorization flow and get an authorization code.
    """
    oauth2_application = oauth2_application[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': oauth2_application.client_id,
        'response_type': 'code',
        'scope': 'read',
        # PKCE
        'code_challenge': '4-as-randomly-generated-by-rolling-a-die',
        'code_challenge_method': 'S256',
    }

    # Initial request - authorization request, should show a form to authorize the application
    response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200, response.headers
    assert f'Authorize {oauth2_application.name}' in str(response.content)

    # But the form mostly just repackages the GET params into a POST request
    query_params['redirect_uri'] = oauth2_application.redirect_uris
    query_params['allow'] = 'Authorize'
    response = user_api_client.post(url, data=query_params)
    assert response.status_code == 302
    assert response.url.startswith(query_params['redirect_uri'])

    # On success, it takes us to the redirect_uri with the code
    assert 'code=' in response.url, response.url
    assert 'error=' not in response.url, response.url


def test_authorize_pkce_required_without_challenge(user_api_client, oauth2_app_pkce_required):
    """
    When pkce_required=True and the client omits code_challenge, the request should be rejected
    with a 302 redirect containing error=invalid_request and state per RFC 6749 §4.1.2.1.
    """
    app = oauth2_app_pkce_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
        'state': 'test-state-value',
    }
    response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 302
    assert 'error=invalid_request' in response.url
    assert 'state=test-state-value' in response.url


def test_authorize_pkce_required_with_empty_challenge(user_api_client, oauth2_app_pkce_required):
    """
    When pkce_required=True and the client sends an empty code_challenge, the request should
    be rejected. An empty string is not a valid code_challenge per RFC 9126 / OAuth 2.1 §7.6.1.
    """
    app = oauth2_app_pkce_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
        'code_challenge': '',
        'code_challenge_method': 'S256',
    }
    response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 302
    assert 'error=invalid_request' in response.url


def test_authorize_pkce_required_with_challenge(user_api_client, oauth2_app_pkce_required):
    """
    When pkce_required=True and the client sends code_challenge, the request should succeed.
    """
    app = oauth2_app_pkce_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
        'code_challenge': 'some-challenge-value',
        'code_challenge_method': 'S256',
    }
    response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200


def test_authorize_pkce_not_required_without_challenge(user_api_client, oauth2_app_pkce_not_required):
    """
    When pkce_required=False and the client omits code_challenge, the request should succeed.
    """
    app = oauth2_app_pkce_not_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
    }
    response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200


def test_authorize_pkce_not_required_with_challenge(user_api_client, oauth2_app_pkce_not_required):
    """
    When pkce_required=False and the client sends code_challenge, the request should succeed.
    """
    app = oauth2_app_pkce_not_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
        'code_challenge': 'some-challenge-value',
        'code_challenge_method': 'S256',
    }
    response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200


def test_authorize_post_pkce_required_without_challenge(user_api_client, oauth2_app_pkce_required):
    """
    When pkce_required=True and the POST form submission omits code_challenge,
    the request should be rejected with a 302 redirect containing error=invalid_request.
    """
    app = oauth2_app_pkce_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    post_data = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
        'allow': 'Authorize',
    }
    response = user_api_client.post(url, data=post_data)
    assert response.status_code == 302
    assert 'error=invalid_request' in response.url


def test_authorize_post_pkce_required_with_challenge(user_api_client, oauth2_app_pkce_required):
    """
    When pkce_required=True and the POST form submission includes code_challenge,
    the request should succeed.
    """
    app = oauth2_app_pkce_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    post_data = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
        'allow': 'Authorize',
        'code_challenge': 'some-challenge-value',
        'code_challenge_method': 'S256',
    }
    response = user_api_client.post(url, data=post_data)
    assert response.status_code == 302
    assert 'code=' in response.url
    assert 'error=' not in response.url


def test_authorize_global_pkce_overrides_app_setting(user_api_client, oauth2_app_pkce_not_required):
    """
    When global PKCE_REQUIRED=True, PKCE should be enforced even if the app has pkce_required=False.
    DOT enforces the global setting during validate_authorization_request() and returns a 302
    redirect with an error, so the request never reaches the per-app check.
    """
    app = oauth2_app_pkce_not_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
    }
    global_pkce_settings = {**settings.OAUTH2_PROVIDER, 'PKCE_REQUIRED': True}
    with override_settings(OAUTH2_PROVIDER=global_pkce_settings):
        response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 302
    assert 'error=invalid_request' in response.url


def test_authorize_global_pkce_with_challenge(user_api_client, oauth2_app_pkce_not_required):
    """
    When global PKCE_REQUIRED=True and the client sends code_challenge, the request should succeed.
    """
    app = oauth2_app_pkce_not_required[0]
    url = get_relative_url("oauth2_provider:authorize")
    query_params = {
        'client_id': app.client_id,
        'response_type': 'code',
        'scope': 'read',
        'redirect_uri': app.redirect_uris,
        'code_challenge': 'some-challenge-value',
        'code_challenge_method': 'S256',
    }
    global_pkce_settings = {**settings.OAUTH2_PROVIDER, 'PKCE_REQUIRED': True}
    with override_settings(OAUTH2_PROVIDER=global_pkce_settings):
        response = user_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200
