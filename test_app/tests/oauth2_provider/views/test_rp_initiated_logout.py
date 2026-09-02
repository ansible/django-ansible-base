import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils.http import urlencode
from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import (
    OAuth2AccessToken,
    OAuth2Application,
    OAuth2IDToken,
    OAuth2RefreshToken,
)


@pytest.fixture
def oidc_enabled_settings():
    """Settings with OIDC enabled and RP-initiated logout configured."""
    return {
        **settings.OAUTH2_PROVIDER,
        'OIDC_ENABLED': True,
        'SCOPES': {'read': 'Read', 'write': 'Write', 'openid': 'OpenID', 'roles': 'Roles'},
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


@pytest.fixture
def oidc_app_factory(randname):
    """Factory for apps that issue HS256 ID tokens (key derived from client_secret, no RSA setup)."""

    def _factory(name_prefix="OIDC App"):
        app = OAuth2Application(
            name=randname(name_prefix),
            redirect_uris="https://example.com/callback",
            post_logout_redirect_uris="https://example.com/callback",
            authorization_grant_type="authorization-code",
            client_type="confidential",
            algorithm=OAuth2Application.HS256_ALGORITHM,
            pkce_required=False,
        )
        secret = app.client_secret  # capture plaintext before it's hashed on save
        app.save()
        return app, secret

    return _factory


def _jwt_claims(jwt_str):
    """Decode (unverified) a JWT payload -- used only to find the IDToken row by jti."""
    payload_b64 = jwt_str.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)  # restore base64 padding
    return json.loads(base64.urlsafe_b64decode(payload_b64.encode()))


def _mint_session(api_client, app, secret):
    """Run the real authorize -> token flow; return (id_token_jwt, id_token, access_token, refresh_token).

    Using the real endpoints guarantees the minted AccessToken carries the `openid` scope
    (requested below), which is what deletion is keyed on.
    """
    authorize_url = get_relative_url("oauth2_provider:authorize")
    response = api_client.post(
        authorize_url,
        data={
            "client_id": app.client_id,
            "response_type": "code",
            "scope": "openid read",
            "redirect_uri": app.redirect_uris,
            "allow": "Authorize",
        },
    )
    assert response.status_code == 302, response.status_code
    code = parse_qs(urlparse(response.url).query)["code"][0]

    token_url = get_relative_url("oauth2_provider:token")
    token_response = api_client.post(
        token_url,
        data=urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": app.redirect_uris,
                "client_id": app.client_id,
                "client_secret": secret,
            }
        ),
        content_type="application/x-www-form-urlencoded",
    )
    # DAB's TokenView returns 201 on token creation (DOT's default is 200); accept either.
    assert token_response.status_code in (200, 201), token_response.status_code
    id_token_jwt = token_response.json()["id_token"]

    id_token_row = OAuth2IDToken.objects.get(jti=_jwt_claims(id_token_jwt)["jti"])
    access_token_row = id_token_row.access_token
    refresh_token_row = OAuth2RefreshToken.objects.get(access_token=access_token_row)
    return id_token_jwt, id_token_row, access_token_row, refresh_token_row


def _assert_session_alive(id_token_row, access_token_row, refresh_token_row):
    assert OAuth2IDToken.objects.filter(pk=id_token_row.pk).exists()
    assert OAuth2AccessToken.objects.filter(pk=access_token_row.pk).exists()
    refresh_token_row.refresh_from_db()
    assert refresh_token_row.revoked is None


def _assert_session_revoked(id_token_row, access_token_row, refresh_token_row):
    # id_token/access_token rows are deleted; refresh_token is marked revoked (access_token nulled).
    assert not OAuth2IDToken.objects.filter(pk=id_token_row.pk).exists()
    assert not OAuth2AccessToken.objects.filter(pk=access_token_row.pk).exists()
    refresh_token_row.refresh_from_db()
    assert refresh_token_row.revoked is not None
    assert refresh_token_row.access_token_id is None


@pytest.mark.django_db
def test_logout_deletes_openid_sessions_for_the_requesting_application(user_api_client, user, random_user, oidc_app_factory, oidc_enabled_settings):
    """Logout revokes the requesting user's openid-scoped sessions for the application
    identified by the logout request (via id_token_hint / client_id resolution) -- other
    applications' sessions for the same user, and other users' sessions, are untouched."""
    app1, secret1 = oidc_app_factory("App One")
    app2, secret2 = oidc_app_factory("App Two")

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        # user: sessions A + B on app1 (same app), session C on app2
        a_jwt, a_id, a_at, a_rt = _mint_session(user_api_client, app1, secret1)
        _b_jwt, b_id, b_at, b_rt = _mint_session(user_api_client, app1, secret1)
        _c_jwt, c_id, c_at, c_rt = _mint_session(user_api_client, app2, secret2)

        # second user: session D on app1
        other_client = APIClient()
        other_client.login(username=random_user.username, password="password")
        _d_jwt, d_id, d_at, d_rt = _mint_session(other_client, app1, secret1)

        # id_token_hint resolves the requesting application (app1) that deletion is narrowed to.
        logout_url = get_relative_url("oauth2_provider:rp-initiated-logout")
        response = user_api_client.get(logout_url + "?" + urlencode({"id_token_hint": a_jwt}))
        assert response.status_code == 302, response.content

    _assert_session_revoked(a_id, a_at, a_rt)
    _assert_session_revoked(b_id, b_at, b_rt)  # same user, same app -> also revoked
    _assert_session_alive(c_id, c_at, c_rt)  # same user, other app -> survives
    _assert_session_alive(d_id, d_at, d_rt)  # other user -> survives


@pytest.mark.django_db
def test_logout_via_post_form_deletes_openid_sessions_for_the_requesting_application(user_api_client, user, oidc_app_factory, oidc_enabled_settings):
    """Same app-scoped guarantee via the POST/form_valid() path (the second do_logout() call site)."""
    app1, secret1 = oidc_app_factory("Form App One")

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        a_jwt, a_id, a_at, a_rt = _mint_session(user_api_client, app1, secret1)
        _b_jwt, b_id, b_at, b_rt = _mint_session(user_api_client, app1, secret1)

        logout_url = get_relative_url("oauth2_provider:rp-initiated-logout")
        response = user_api_client.post(logout_url, {"id_token_hint": a_jwt, "allow": True})
        assert response.status_code == 302, response.content

    _assert_session_revoked(a_id, a_at, a_rt)
    _assert_session_revoked(b_id, b_at, b_rt)


@pytest.mark.django_db
def test_logout_without_hint_deletes_openid_tokens_across_all_apps(user_api_client, user, oidc_app_factory, oidc_enabled_settings):
    """Without id_token_hint or client_id, no application can be identified, so deletion
    falls back to all of the user's openid sessions (across every application)."""
    app1, secret1 = oidc_app_factory("No Hint App One")
    app2, secret2 = oidc_app_factory("No Hint App Two")

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        _jwt1, id_row1, at_row1, rt_row1 = _mint_session(user_api_client, app1, secret1)
        _jwt2, id_row2, at_row2, rt_row2 = _mint_session(user_api_client, app2, secret2)

        logout_url = get_relative_url("oauth2_provider:rp-initiated-logout")
        response = user_api_client.post(logout_url, {"allow": True})
        assert response.status_code == 302, response.content

    _assert_session_revoked(id_row1, at_row1, rt_row1)
    _assert_session_revoked(id_row2, at_row2, rt_row2)


@pytest.mark.django_db
def test_logout_cross_user_hint_revokes_nothing(user_api_client, user, random_user, oidc_app_factory, oidc_enabled_settings):
    """A user may only revoke their OWN openid sessions: submitting another user's hint does not
    delete that user's tokens, since deletion is scoped to request.user, not to the hint's user."""
    app1, secret1 = oidc_app_factory("Cross User App")

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        # user B mints a session; user A (user_api_client) then tries to log it out using B's hint.
        other_client = APIClient()
        other_client.login(username=random_user.username, password="password")
        b_jwt, b_id, b_at, b_rt = _mint_session(other_client, app1, secret1)

        logout_url = get_relative_url("oauth2_provider:rp-initiated-logout")
        response = user_api_client.post(logout_url, {"id_token_hint": b_jwt, "allow": True})
        assert response.status_code == 302, response.status_code

    _assert_session_alive(b_id, b_at, b_rt)  # B's session untouched by A


@pytest.mark.django_db
def test_logout_preserves_non_oidc_tokens(user_api_client, user, oauth2_user_pat, oauth2_user_application_token, oidc_app_factory, oidc_enabled_settings):
    """The scoped path must not touch unrelated non-OIDC tokens -- the core production incident.

    Uses an application-scoped token (which stock DOT's delete-all WOULD wipe) plus a PAT.
    """
    app, secret = oidc_app_factory("Mixed Token App")

    with override_settings(OAUTH2_PROVIDER=oidc_enabled_settings):
        a_jwt, a_id, a_at, a_rt = _mint_session(user_api_client, app, secret)

        logout_url = get_relative_url("oauth2_provider:rp-initiated-logout")
        response = user_api_client.get(logout_url + "?" + urlencode({"id_token_hint": a_jwt}))
        assert response.status_code == 302, response.status_code

    _assert_session_revoked(a_id, a_at, a_rt)  # targeted OIDC session gone
    assert OAuth2AccessToken.objects.filter(pk=oauth2_user_application_token.pk).exists()  # app token survives
    assert OAuth2AccessToken.objects.filter(pk=oauth2_user_pat.pk).exists()  # PAT survives


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
