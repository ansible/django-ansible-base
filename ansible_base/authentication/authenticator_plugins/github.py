import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.github import GithubOAuth2

from ansible_base.authentication.authenticator_configurators.github import GithubConfiguration
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github')


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubOAuth2, AbstractAuthenticatorPlugin):  # type: ignore[override]
    configuration_class = GithubConfiguration
    logger = logger
    type = "github"
    display_name = _("GitHub")
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
