from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url


@pytest.fixture
def oidc_enabled_settings():
    """Settings with OIDC enabled and RP-initiated logout configured."""
    return {
        **settings.OAUTH2_PROVIDER,
        'OIDC_ENABLED': True,
        'OIDC_RP_INITIATED_LOGOUT_ENABLED': True,
        'OIDC_RP_INITIATED_LOGOUT_DELETE_TOKENS': True,
        'OIDC_RP_INITIATED_LOGOUT_STRICT_REDIRECT_URIS': True,
        'OIDC_RP_INITIATED_LOGOUT_ALWAYS_PROMPT': False,
        'OIDC_RP_INITIATED_LOGOUT_ACCEPT_EXPIRED_TOKENS': False,
    }


@pytest.fixture
def oauth2_application_with_logout_redirect(oauth2_application):
    """OAuth2 application configured with post_logout_redirect_uris for RP-initiated logout tests."""
    app, secret = oauth2_application
    app.post_logout_redirect_uris = 'https://example.com/callback'
    app.save()
    return app, secret


@pytest.mark.django_db
def test_logout_endpoint_exists(client, oidc_enabled_settings):
    """
    Test that the /o/logout/ endpoint is accessible when OIDC is enabled.
    """
    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        assert url is not None
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
def test_logout_endpoint_requires_oidc_enabled(client):
    """
    Test that the logout endpoint returns an error when OIDC is not enabled.
    """
    oidc_disabled_settings = {
        **settings.OAUTH2_PROVIDER,
        'OIDC_ENABLED': False,
    }
    with override_settings(OAUTH2_PROVIDER=oidc_disabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = client.get(url)
        # RPInitiatedLogoutView returns 404 when OIDC is disabled
        assert response.status_code == 404


@pytest.mark.django_db
def test_logout_endpoint_requires_rp_logout_enabled(client):
    """
    Test that the logout endpoint returns an error when RP-initiated logout is not enabled.
    """
    rp_logout_disabled = {
        **settings.OAUTH2_PROVIDER,
        'OIDC_ENABLED': True,
        'OIDC_RP_INITIATED_LOGOUT_ENABLED': False,
    }
    with override_settings(OAUTH2_PROVIDER=rp_logout_disabled):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = client.get(url)
        # RPInitiatedLogoutView returns 404 when RP-initiated logout is disabled
        assert response.status_code == 404


@pytest.mark.django_db
def test_logout_get_request_displays_form(client, oidc_enabled_settings):
    """
    Test that GET request to logout endpoint displays a logout confirmation form.
    """
    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = client.get(url)
        # Should display a form or confirmation page
        assert response.status_code == 200
        assert b'logout' in response.content.lower() or b'sign out' in response.content.lower()


@pytest.mark.django_db
def test_logout_with_post_logout_redirect_uri(user_api_client, oidc_enabled_settings, oauth2_application_with_logout_redirect):
    """
    Test logout with a valid post_logout_redirect_uri parameter redirects after consent.
    """
    app = oauth2_application_with_logout_redirect[0]
    redirect_uri = 'https://example.com/callback'

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = user_api_client.post(
            url,
            {
                'post_logout_redirect_uri': redirect_uri,
                'client_id': app.client_id,
                'allow': True,
            },
        )

        assert response.status_code == 302
        assert redirect_uri in response['Location']


@pytest.mark.django_db
def test_logout_with_invalid_redirect_uri_when_strict(client, oidc_enabled_settings, oauth2_application):
    """
    Test that logout rejects invalid redirect URIs when STRICT_REDIRECT_URIS is enabled.
    """
    app = oauth2_application[0]
    invalid_redirect = 'https://malicious-site.com/callback'

    strict_settings = {
        **oidc_enabled_settings,
        'OIDC_RP_INITIATED_LOGOUT_STRICT_REDIRECT_URIS': True,
    }

    with override_settings(OAUTH2_PROVIDER=strict_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = client.post(
            url,
            {
                'post_logout_redirect_uri': invalid_redirect,
                'client_id': app.client_id,
                'allow': True,
            },
        )

        assert response.status_code == 400
        assert b'malicious-site.com' not in response.content


@pytest.mark.django_db
def test_logout_with_state_parameter(user_api_client, oidc_enabled_settings, oauth2_application_with_logout_redirect):
    """
    Test that the state parameter is preserved in the redirect after logout.
    """
    app = oauth2_application_with_logout_redirect[0]
    redirect_uri = 'https://example.com/callback'
    state = 'test-state-value-123'

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = user_api_client.post(
            url,
            {
                'post_logout_redirect_uri': redirect_uri,
                'client_id': app.client_id,
                'state': state,
                'allow': True,
            },
        )

        assert response.status_code == 302
        redirect_url = response['Location']
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        assert 'state' in params, "state parameter was not preserved in the redirect URL"
        assert params['state'][0] == state


@pytest.mark.django_db
def test_logout_endpoint_in_oidc_discovery(client, oidc_enabled_settings):
    """
    Test that the logout endpoint is advertised in the OIDC discovery document.
    """
    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:oidc-connect-discovery-info')
        response = client.get(url)
        assert response.status_code == 200

        discovery = response.json()
        # Check if end_session_endpoint is present in discovery
        assert 'end_session_endpoint' in discovery
        assert 'logout' in discovery['end_session_endpoint']


@pytest.mark.django_db
def test_logout_without_prompt_when_configured(user_api_client, oidc_enabled_settings, oauth2_application_with_logout_redirect):
    """
    Test logout with ALWAYS_PROMPT=False still prompts without id_token_hint,
    but proceeds with explicit consent.
    """
    app = oauth2_application_with_logout_redirect[0]
    redirect_uri = 'https://example.com/callback'

    no_prompt_settings = {
        **oidc_enabled_settings,
        'OIDC_RP_INITIATED_LOGOUT_ALWAYS_PROMPT': False,
    }

    with override_settings(OAUTH2_PROVIDER=no_prompt_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = user_api_client.post(
            url,
            {
                'post_logout_redirect_uri': redirect_uri,
                'client_id': app.client_id,
                'allow': True,
            },
        )

        assert response.status_code == 302
        assert redirect_uri in response['Location']


@pytest.mark.django_db
def test_logout_url_pattern_name(client, oidc_enabled_settings):
    """
    Test that the logout URL pattern has the expected name 'rp-initiated-logout'.
    """
    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        # This test verifies that get_relative_url works with the expected name
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        assert url is not None
        assert '/o/logout/' in url


@pytest.mark.django_db
def test_logout_url_matches_spec(client, oidc_enabled_settings):
    """
    Test that the logout URL matches the OIDC RP-Initiated Logout spec.
    The endpoint should be accessible at /o/logout/
    """
    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        response = client.get('/o/logout/')
        assert response.status_code == 200


@pytest.mark.django_db
def test_logout_accepts_both_get_and_post(client, oidc_enabled_settings):
    """
    Test that the logout endpoint accepts both GET and POST requests.
    """
    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')

        get_response = client.get(url)
        assert get_response.status_code == 200

        # POST without consent (no allow=True) is denied
        post_response = client.post(url)
        assert post_response.status_code == 400


@pytest.mark.django_db
def test_logout_with_client_id_only(client, oidc_enabled_settings, oauth2_application):
    """
    Test logout with only client_id parameter (no ID token hint or consent) is denied.
    """
    app = oauth2_application[0]

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = client.post(
            url,
            {
                'client_id': app.client_id,
            },
        )

        assert response.status_code == 400


@pytest.mark.django_db
def test_logout_without_parameters(client, oidc_enabled_settings):
    """
    Test that POST without any parameters (no consent) is denied.
    """
    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        url = get_relative_url('oauth2_provider:rp-initiated-logout')
        response = client.post(url)

        assert response.status_code == 400


@pytest.mark.django_db
def test_logout_configuration_defaults():
    """
    Test that the default configuration includes the expected RP-initiated logout settings.
    """
    # Verify that our default settings are present
    oauth2_settings = settings.OAUTH2_PROVIDER

    assert 'OIDC_RP_INITIATED_LOGOUT_ENABLED' in oauth2_settings
    assert oauth2_settings['OIDC_RP_INITIATED_LOGOUT_ENABLED'] is True

    assert 'OIDC_RP_INITIATED_LOGOUT_DELETE_TOKENS' in oauth2_settings
    assert oauth2_settings['OIDC_RP_INITIATED_LOGOUT_DELETE_TOKENS'] is True

    assert 'OIDC_RP_INITIATED_LOGOUT_STRICT_REDIRECT_URIS' in oauth2_settings
    assert oauth2_settings['OIDC_RP_INITIATED_LOGOUT_STRICT_REDIRECT_URIS'] is True

    assert 'OIDC_RP_INITIATED_LOGOUT_ALWAYS_PROMPT' in oauth2_settings
    assert oauth2_settings['OIDC_RP_INITIATED_LOGOUT_ALWAYS_PROMPT'] is False

    assert 'OIDC_RP_INITIATED_LOGOUT_ACCEPT_EXPIRED_TOKENS' in oauth2_settings
    assert oauth2_settings['OIDC_RP_INITIATED_LOGOUT_ACCEPT_EXPIRED_TOKENS'] is False
