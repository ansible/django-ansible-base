from datetime import timedelta

from django.utils.timezone import now
from oauth2_provider import views as oauth_views
from oauthlib import oauth2
from rest_framework import permissions
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken
from ansible_base.oauth2_provider.serializers import OAuth2TokenSerializer


class TokenView(oauth_views.TokenView, AnsibleBaseDjangoAppApiView):
    # There is a big flow of logic that happens around this behind the scenes.
    #
    # oauth2_provider.views.TokenView inherits from oauth2_provider.views.mixins.OAuthLibMixin
    # That's where this method comes from originally.
    # Then *that* method ends up calling oauth2_provider.oauth2_backends.OAuthLibCore.create_token_response
    # Then *that* method ends up (ultimately) calling oauthlib.oauth2.rfc6749....
    def create_token_response(self, request):
        # Django OAuth2 Toolkit has a bug whereby refresh tokens are *never*
        # properly expired (ugh):
        #
        # https://github.com/jazzband/django-oauth-toolkit/issues/746
        #
        # This code detects and auto-expires them on refresh grant
        # requests.
        if request.POST.get('grant_type') == 'refresh_token' and 'refresh_token' in request.POST:
            refresh_token = OAuth2RefreshToken.objects.filter(token=request.POST['refresh_token']).first()
            if refresh_token:
                expire_seconds = get_setting('OAUTH2_PROVIDER', {}).get('REFRESH_TOKEN_EXPIRE_SECONDS', 0)
                if refresh_token.created + timedelta(seconds=expire_seconds) < now():
                    return request.build_absolute_uri(), {}, 'The refresh token has expired.', '403'

        core = self.get_oauthlib_core()  # oauth2_provider.views.mixins.OAuthLibMixin.create_token_response

        # oauth2_provider.oauth2_backends.OAuthLibCore.create_token_response
        # (we override this so we can implement our own error handling to be compatible with AWX)
        uri, http_method, body, headers = core._extract_params(request)
        extra_credentials = core._get_extra_credentials(request)
        try:
            headers, body, status = core.server.create_token_response(uri, http_method, body, headers, extra_credentials)
            uri = headers.get("Location", None)
            status = 201 if request.method == 'POST' and status == 200 else status
            return uri, headers, body, status
        except oauth2.AccessDeniedError as e:
            return request.build_absolute_uri(), {}, str(e), 403  # Compat with AWX
        except oauth2.OAuth2Error as e:
            return request.build_absolute_uri(), {}, str(e), e.status_code


class OAuth2TokenViewSet(ModelViewSet, AnsibleBaseDjangoAppApiView):
    queryset = OAuth2AccessToken.objects.all()
    serializer_class = OAuth2TokenSerializer
    permission_classes = [permissions.IsAuthenticated]
