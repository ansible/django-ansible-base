from datetime import timedelta

from django.conf import settings
from django.utils.timezone import now
from oauth2_provider.views import TokenView
from oauthlib.oauth2 import AccessDeniedError

from ansible_base.oauth2_provider.models import OAuth2RefreshToken


class TokenView(TokenView):
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
                expire_seconds = settings.OAUTH2_PROVIDER.get('REFRESH_TOKEN_EXPIRE_SECONDS', 0)
                if refresh_token.created + timedelta(seconds=expire_seconds) < now():
                    return request.build_absolute_uri(), {}, 'The refresh token has expired.', '403'
        try:
            return super(TokenView, self).create_token_response(request)
        except AccessDeniedError as e:
            return request.build_absolute_uri(), {}, str(e), '403'
