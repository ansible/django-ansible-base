from django.utils.http import urlencode

from ansible_base.lib.utils.response import get_relative_url


def test_oauth2_provider_authorize_view_as_admin(admin_api_client):
    """
    As an admin, accessing /o/authorize/ without client_id parameter should return a 400 error.
    """
    url = get_relative_url("authorize")
    response = admin_api_client.get(url)

    assert response.status_code == 400
    assert 'Missing client_id parameter.' in str(response.content)


def test_oauth2_provider_authorize_view_anon(client, settings):
    """
    As an anonymous user, accessing /o/authorize/ should redirect to the login page.
    """
    url = get_relative_url("authorize")
    response = client.get(url)

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)


def test_oauth2_provider_authorize_view_flow(user_api_client, oauth2_application):
    """
    As a user, I should be able to complete the authorization flow and get an authorization code.
    """
    oauth2_application = oauth2_application[0]
    url = get_relative_url("authorize")
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
