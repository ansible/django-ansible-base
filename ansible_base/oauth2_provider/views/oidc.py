import json
import logging

from django.contrib.auth import logout
from django.urls import reverse
from jwcrypto import jwt
from jwcrypto.common import JWException
from jwcrypto.jws import InvalidJWSObject, JWS
from jwcrypto.jwt import JWTExpired
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_id_token_model,
    get_refresh_token_model,
)
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views import RPInitiatedLogoutView as _DOTRPInitiatedLogoutView
from oauth2_provider.views.oidc import ConnectDiscoveryInfoView
from oauthlib.common import add_params_to_uri

logger = logging.getLogger('ansible_base.oauth2_provider.views.oidc')

Application = get_application_model()


def _jwk_key_for_id_token_hint(id_token_hint):
    """Resolve the signing key for an id_token_hint JWT using public DOT model APIs."""
    try:
        unverified_token = JWS()
        unverified_token.deserialize(id_token_hint)
        claims = json.loads(unverified_token.objects["payload"].decode("utf-8"))
    except (InvalidJWSObject, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    audience = claims.get("aud")
    if not audience:
        return None
    if isinstance(audience, str):
        audience = [audience]

    application = Application.objects.filter(client_id__in=audience).first()
    if not application:
        return None
    return application.jwk_key


def load_id_token_from_hint(request, id_token_hint):
    """Decode and verify an id_token_hint JWT, returning the matching IDToken row."""
    key = _jwk_key_for_id_token_hint(id_token_hint)
    if not key:
        return None, None

    IDToken = get_id_token_model()
    validator = oauth2_settings.OAUTH2_VALIDATOR_CLASS()

    try:
        if oauth2_settings.OIDC_RP_INITIATED_LOGOUT_ACCEPT_EXPIRED_TOKENS:
            check_claims = {}
        else:
            check_claims = None
        jwt_token = jwt.JWT(key=key, jwt=id_token_hint, check_claims=check_claims)
        claims = json.loads(jwt_token.claims)
    except (JWException, JWTExpired):
        return None, None

    if "iss" not in claims or claims["iss"] != validator.get_oidc_issuer_endpoint(request):
        return None, None

    try:
        return IDToken.objects.get(jti=claims["jti"]), claims
    except IDToken.DoesNotExist:
        return None, None


class DiscoveryInfoView(ConnectDiscoveryInfoView):
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)

        if response.status_code != 200:
            return response

        data = json.loads(response.content)
        # Uses build_absolute_uri() consistent with how the parent ConnectDiscoveryInfoView
        # builds authorization_endpoint, token_endpoint, etc. Host header injection is
        # mitigated by Django's ALLOWED_HOSTS (enforced when DEBUG=False).
        data["revocation_endpoint"] = request.build_absolute_uri(reverse("oauth2_provider:revoke-token"))
        # should be removed once DAB upgrades from django-oauth-toolkit 2.3.0 to >=2.4.0,
        # which adds code_challenge_methods_supported to ConnectDiscoveryInfoView natively.
        data["code_challenge_methods_supported"] = ["S256", "plain"]

        response.content = json.dumps(data)
        return response


class RPInitiatedLogoutView(_DOTRPInitiatedLogoutView):
    """
    Scope RP-Initiated Logout token deletion to the single session (the
    AccessToken/RefreshToken/IDToken triplet) identified by `id_token_hint`.

    DOT's stock do_logout() instead deletes every token the user owns across all
    applications, destroying unrelated long-lived API tokens on logout. We revoke
    only the triplet tied to `id_token_hint`; if it is missing/invalid/unresolvable,
    we delete nothing (session logout still happens) rather than falling back to
    DOT's delete-all behavior.
    """

    def do_logout(self, application=None, post_logout_redirect_uri=None, state=None, token_user=None):
        # DOT 2.3.0's do_logout() with the deletion block swapped for scoped deletion.
        # The logout()+redirect tail is duplicated (not super()) because DOT gives no
        # smaller override seam; re-audit against DOT when the pin is bumped.
        if oauth2_settings.OIDC_RP_INITIATED_LOGOUT_DELETE_TOKENS:
            self._revoke_session_tokens()

        # Logout in Django
        logout(self.request)

        if post_logout_redirect_uri:
            if state:
                return OAuth2ResponseRedirect(
                    add_params_to_uri(post_logout_redirect_uri, [("state", state)]),
                    application.get_allowed_schemes(),
                )
            return OAuth2ResponseRedirect(post_logout_redirect_uri, application.get_allowed_schemes())
        return OAuth2ResponseRedirect(
            self.request.build_absolute_uri("/"),
            oauth2_settings.ALLOWED_REDIRECT_URI_SCHEMES,
        )

    def _revoke_session_tokens(self):
        """Revoke only the authenticated user's own IDToken/AccessToken/RefreshToken tied to id_token_hint."""
        # self.oidc_data is unusable here: dispatch() resets it to {} and it's only
        # populated on the form-rendering GET branch, so read the hint off the request
        # (POST hidden field, or GET for the no-prompt short-circuit).
        id_token_hint = self.request.POST.get("id_token_hint") or self.request.GET.get("id_token_hint")
        if not id_token_hint:
            # Can't identify the session -> delete nothing (no delete-all fallback).
            return

        id_token, _claims = load_id_token_from_hint(self.request, id_token_hint)
        if id_token is None:
            # Bad signature, expired, or unknown jti.
            return

        request_user_id = getattr(self.request.user, 'id', None)
        if request_user_id is None or id_token.user_id != request_user_id:
            logger.warning(
                "RP-Initiated Logout: id_token_hint (jti=%s) does not belong to the logging-out user; skipping token deletion.",
                id_token.jti,
            )
            return

        AccessToken = get_access_token_model()
        RefreshToken = get_refresh_token_model()

        try:
            access_token = id_token.access_token
        except AccessToken.DoesNotExist:
            access_token = None

        refresh_token = None
        if access_token is not None:
            try:
                refresh_token = access_token.refresh_token
            except RefreshToken.DoesNotExist:
                refresh_token = None

        # DOT's order: id_token (cascade-deletes its access token), then access token
        # (no-op if already gone), then refresh token (marked revoked, not deleted).
        id_token.revoke()
        if access_token is not None:
            access_token.revoke()
        if refresh_token is not None:
            refresh_token.revoke()
