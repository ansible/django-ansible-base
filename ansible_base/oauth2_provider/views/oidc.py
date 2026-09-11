import json

from django.contrib.auth import logout
from django.urls import reverse
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.models import get_access_token_model, get_refresh_token_model
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views import RPInitiatedLogoutView as _DOTRPInitiatedLogoutView
from oauth2_provider.views.oidc import ConnectDiscoveryInfoView
from oauthlib.common import add_params_to_uri


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
    Scope RP-Initiated Logout revocation to the requesting user's own `openid`-scoped
    tokens for the requesting application -- not DOT's stock do_logout(), which
    deletes every token the user owns across ALL applications, including unrelated
    long-lived API tokens (PATs, application tokens).
    """

    def do_logout(self, application=None, post_logout_redirect_uri=None, state=None, token_user=None):
        # DOT 2.3.0's do_logout(), deletion block swapped for scoped deletion.
        # No smaller override seam exists; re-audit against DOT when the pin is bumped.
        if oauth2_settings.OIDC_RP_INITIATED_LOGOUT_DELETE_TOKENS:
            self._revoke_openid_tokens(self.request.user, application)

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

    def _revoke_openid_tokens(self, user, application=None):
        """Revoke the user's openid-scoped AccessTokens (plus linked id/refresh
        tokens), narrowed to `application` when the logout request identifies one."""
        if user is None or not user.is_authenticated:
            return

        access_token_model = get_access_token_model()
        refresh_token_model = get_refresh_token_model()

        access_tokens = access_token_model.objects.filter(user=user, scope__regex=r"(^|\s)openid(\s|$)")
        if application is not None:
            access_tokens = access_tokens.filter(application=application)

        for access_token in access_tokens:
            # id_token is a direct nullable FK on AccessToken -- None, not DoesNotExist, when unset.
            id_token = access_token.id_token

            try:
                refresh_token = access_token.refresh_token
            except refresh_token_model.DoesNotExist:
                refresh_token = None

            if id_token is not None:
                id_token.revoke()
            access_token.revoke()
            if refresh_token is not None:
                refresh_token.revoke()
