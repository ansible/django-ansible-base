from oauth2_provider import views as oauth_views
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.models import get_application_model
from oauthlib.oauth2.rfc6749.errors import InvalidRequestError

from ansible_base.lib.utils.settings import get_setting


class AuthorizationView(oauth_views.AuthorizationView):
    """
    Extends DOT's AuthorizationView to add per-application PKCE enforcement.

    DOT only supports a global PKCE_REQUIRED setting. This subclass adds an
    application-level ``pkce_required`` field check so individual apps can
    require PKCE even when the global setting is off. When global PKCE_REQUIRED
    is True, DOT already enforces PKCE for all apps and this class defers to it.

    Overrides:
      - get(): pre-validates the request to extract credentials, then runs the
        per-app PKCE check before delegating to super().get(). This causes
        validate_authorization_request() to run twice (ours + DOT's), but the
        call is idempotent and avoids copying DOT's get() internals.
      - form_valid(): runs the same per-app PKCE check on POST submissions
        before delegating to super().form_valid().
    """

    def get(self, request, *args, **kwargs):
        # Intentional double call: validate_authorization_request() runs here
        # to extract credentials for the per-app PKCE check, then again inside
        # super().get(). The call is idempotent (read-only, no side effects),
        # and this avoids copying DOT's get() internals.
        try:
            _, credentials = self.validate_authorization_request(request)
        except OAuthToolkitError as error:
            return self.error_response(error, application=None)

        error_response = self._check_pkce_required(credentials["client_id"], credentials)
        if error_response is not None:
            return error_response

        return super().get(request, *args, **kwargs)

    def _check_pkce_required(self, client_id, credentials):
        """Return an error response if the app requires PKCE and no code_challenge was provided, else None."""
        application = get_application_model().objects.get(client_id=client_id)

        pkce_required_globally = get_setting('OAUTH2_PROVIDER', {}).get('PKCE_REQUIRED', False)
        if not pkce_required_globally and application.pkce_required and not credentials.get("code_challenge"):
            redirect_uri = credentials.get("redirect_uri")
            error = InvalidRequestError(
                description="This application requires PKCE. Include a code_challenge parameter.",
                state=credentials.get("state"),
            )
            error.redirect_uri = redirect_uri
            return self.error_response(OAuthToolkitError(error=error), application=application)

        return None

    def form_valid(self, form):
        credentials = {k: form.cleaned_data.get(k) for k in ("code_challenge", "code_challenge_method", "redirect_uri", "state") if form.cleaned_data.get(k)}
        error_response = self._check_pkce_required(form.cleaned_data["client_id"], credentials)
        if error_response is not None:
            return error_response

        return super().form_valid(form)
