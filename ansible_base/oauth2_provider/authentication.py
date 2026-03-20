import hashlib
import logging

from django.utils.encoding import smart_str
from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from oauth2_provider.oauth2_backends import OAuthLibCore as _OAuthLibCore
from rest_framework.exceptions import UnsupportedMediaType

from ansible_base.lib.logging import log_auth_event
from ansible_base.lib.utils.hashing import hash_string

logger = logging.getLogger('ansible_base.oauth2_provider.authentication')


class OAuthLibCore(_OAuthLibCore):
    def extract_body(self, request):
        try:
            return request.POST.items()
        except UnsupportedMediaType:
            return ()

    def _extract_params(self, request):
        # Hash the bearer token before oauthlib processes it, since tokens
        # are stored as SHA-256 hashes in the database. This covers all
        # DOT flows (verify_request, create_userinfo_response, etc.).
        bearer_token = request.META.get('HTTP_AUTHORIZATION', '')
        did_hash = False
        # (AAP-68669) Accommodate the ansible-galaxy CLI, which sends OAuth tokens
        # prefixed with `Token ` instead of `Bearer ` (deviates from RFC 6750).
        if bearer_token.lower().startswith(("bearer ", "token ")):
            token_component = bearer_token.split(' ', 1)[1]
            hashed = hash_string(token_component, hasher=hashlib.sha256, algo="sha256")
            request.META['HTTP_AUTHORIZATION'] = f"Bearer {hashed}"
            did_hash = True

        try:
            return super()._extract_params(request)
        finally:
            if did_hash:
                request.META['HTTP_AUTHORIZATION'] = bearer_token


class LoggedOAuth2Authentication(OAuth2Authentication):
    def authenticate(self, request):
        # Token hashing is handled by OAuthLibCore.verify_request() — no need
        # to hash here. We only add audit logging on successful auth.
        ret = super().authenticate(request)

        if ret:
            user, token = ret
            username = user.username if user else '<none>'
            oauth2_application_pk = token.application.pk if token.application else "N/A"
            oauth2_application_name = token.application.name if token.application else "Personal Access Token"
            log_auth_event(
                smart_str(
                    u"User {} performed a {} to {} through the API using OAuth 2 token {} for OAuth2 application {} ({}).".format(
                        username, request.method, request.path, token.pk, oauth2_application_pk, oauth2_application_name
                    )
                )
            )
            # TODO: check oauth_scopes when we have RBAC in Gateway
            if user is not None:
                setattr(user, 'oauth_scopes', [x for x in token.scope.split() if x])
        return ret
