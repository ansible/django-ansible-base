import logging

from django.utils.encoding import smart_str
from oauth2_provider.contrib.rest_framework import OAuth2Authentication

logger = logging.getLogger('ansible_base.authentication.oauth2')


class LoggedOAuth2Authentication(OAuth2Authentication):
    def authenticate(self, request):
        ret = super().authenticate(request)
        if ret:
            user, token = ret
            username = user.username if user else '<none>'
            logger.info(
                smart_str(u"User {} performed a {} to {} through the API using OAuth 2 token {}.".format(username, request.method, request.path, token.pk))
            )
            # TODO: check oauth_scopes when we have RBAC in Gateway
            setattr(user, 'oauth_scopes', [x for x in token.scope.split() if x])
        return ret
