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

        redirect_uri = credentials.get("redirect_uri")

        app_model = get_application_model()
        try:
            application = app_model.objects.get(client_id=credentials["client_id"])
        except app_model.DoesNotExist:
            error = InvalidRequestError(description="Invalid client_id.")
            error.redirect_uri = redirect_uri
            return self.error_response(OAuthToolkitError(error=error), application=None)

        pkce_required_globally = get_setting('OAUTH2_PROVIDER', {}).get('PKCE_REQUIRED', False)
        if (application.pkce_required or pkce_required_globally) and "code_challenge" not in credentials:
            error = InvalidRequestError(description="This application requires PKCE. Include a code_challenge parameter.")
            error.redirect_uri = redirect_uri
            return self.error_response(OAuthToolkitError(error=error), application=application)

        kwargs["scopes"] = scopes
        kwargs["credentials"] = credentials
        kwargs.update(credentials)
        self.oauth2_data = kwargs
        kwargs["application"] = application

        return self.render_to_response(self.get_context_data(**kwargs))
