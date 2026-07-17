from oauth2_provider import views as oauth_views
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.models import get_application_model
from oauthlib.oauth2.rfc6749.errors import InvalidRequestError

from ansible_base.lib.utils.settings import get_setting


class AuthorizationView(oauth_views.AuthorizationView):
    def get(self, request, *args, **kwargs):
        try:
            scopes, credentials = self.validate_authorization_request(request)
        except OAuthToolkitError as error:
            return self.error_response(error, application=None)

        error_response = self._check_pkce_required(credentials["client_id"], credentials)
        if error_response is not None:
            return error_response

        return super().get(request, *args, **kwargs)

    def _check_pkce_required(self, client_id, credentials):
        application = get_application_model().objects.get(client_id=client_id)

        pkce_required_globally = get_setting('OAUTH2_PROVIDER', {}).get('PKCE_REQUIRED', False)
        if (application.pkce_required or pkce_required_globally) and not credentials.get("code_challenge"):
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
