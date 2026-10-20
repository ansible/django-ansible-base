import logging

from social_core.backends.github_enterprise import GithubEnterpriseOAuth2

from ansible_base.authentication.authenticator_configurators.github import GithubEnterpriseConfiguration
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_enterprise')


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubEnterpriseOAuth2, AbstractAuthenticatorPlugin):  # type: ignore[override]
    configuration_class = GithubEnterpriseConfiguration
    logger = logger
    type = "github-enterprise"
    display_name = _("GitHub Enterprise")
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
