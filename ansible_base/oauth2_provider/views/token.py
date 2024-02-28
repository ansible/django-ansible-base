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
        try:
            return super(TokenView, self).create_token_response(request)
        except oauth2.AccessDeniedError as e:
            return request.build_absolute_uri(), {}, str(e), '403'


class OAuth2TokenViewSet(ModelViewSet, AnsibleBaseDjangoAppApiView):
    queryset = OAuth2AccessToken.objects.all()
    serializer_class = OAuth2TokenSerializer
    permission_classes = [permissions.IsAuthenticated]
