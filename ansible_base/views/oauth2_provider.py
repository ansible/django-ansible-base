from collections import OrderedDict
from datetime import timedelta

from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from oauth2_provider import views as oauth_views
from oauthlib import oauth2
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.reverse import _reverse
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from ansible_base.models.oauth2_provider import OAuth2AccessToken, OAuth2Application, OAuth2RefreshToken
from ansible_base.serializers.oauth2_provider import OAuth2ApplicationSerializer, OAuth2TokenSerializer
from ansible_base.utils.settings import get_setting


class TokenView(oauth_views.TokenView):
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


class OAuth2ApplicationViewSet(ModelViewSet):
    # model = OAuth2Application
    queryset = OAuth2Application.objects.all()
    serializer_class = OAuth2ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]


class OAuth2TokenViewSet(ModelViewSet):
    model = OAuth2AccessToken
    serializer_class = OAuth2TokenSerializer
    permission_classes = [permissions.IsAuthenticated]


class ApiOAuthAuthorizationRootView(APIView):
    permission_classes = (permissions.AllowAny,)
    name = _("API OAuth 2 Authorization Root")
    versioning_class = None
    swagger_topic = 'Authentication'

    def get(self, request, format=None):
        data = OrderedDict()
        data['authorize'] = _reverse('authorize')
        data['token'] = _reverse('token')
        data['revoke_token'] = _reverse('revoke-token')
        return Response(data)
