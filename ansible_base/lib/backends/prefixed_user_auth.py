import logging

from django.conf import settings
from django.contrib.auth.backends import ModelBackend

PREFIX = getattr(settings, "RENAMED_USERNAME_PREFIX", None)
logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_enterprise_team')


class PrefixedUserAuthenticationMixin:
    def authenticate(self, request, **kwargs):
        if not PREFIX:
            return None
        if username := kwargs.get("username", None):
            if not username.startswith(PREFIX):
                kwargs["username"] = PREFIX + username
                return super().authenticate(request, **kwargs)


class PrefixedUserAuthBackend(PrefixedUserAuthenticationMixin, ModelBackend):
    pass
