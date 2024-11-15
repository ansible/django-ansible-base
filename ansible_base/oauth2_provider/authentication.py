import hashlib
import logging

from django.utils.encoding import smart_str
from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from oauth2_provider.oauth2_backends import OAuthLibCore as _OAuthLibCore
from rest_framework.exceptions import UnsupportedMediaType

from ansible_base.lib.utils.hashing import hash_string

logger = logging.getLogger('ansible_base.oauth2_provider.authentication')


class OAuthLibCore(_OAuthLibCore):
    def extract_body(self, request):
        try:
            return request.POST.items()
        except UnsupportedMediaType:
            return ()


class LoggedOAuth2Authentication(OAuth2Authentication):
    def authenticate(self, request):
        # sha256 the bearer token. We store the hash in the database
        # and this gives us a place to hash the incoming token for comparison
        did_hash_token = False
        bearer_token = request.META.get('HTTP_AUTHORIZATION')
        if bearer_token and bearer_token.lower().startswith('bearer '):
            token_component = bearer_token.split(' ', 1)[1]
            hashed = hash_string(token_component, hasher=hashlib.sha256, algo="sha256")
            did_hash_token = True
            request.META['HTTP_AUTHORIZATION'] = f"Bearer {hashed}"

        # We don't /really/ want to modify the request, so after we're done authing,
        # revert what we did above.
        try:
            ret = super().authenticate(request)
        finally:
            if did_hash_token:
                request.META['HTTP_AUTHORIZATION'] = bearer_token

        if ret:
            user, token = ret
            username = user.username if user else '<none>'
            logger.info(
                smart_str(u"User {} performed a {} to {} through the API using OAuth 2 token {}.".format(username, request.method, request.path, token.pk))
            )
            # TODO: check oauth_scopes when we have RBAC in Gateway
            setattr(user, 'oauth_scopes', [x for x in token.scope.split() if x])
        return ret
