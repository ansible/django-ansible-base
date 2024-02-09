import logging

from social_core.backends.github import GithubTeamOAuth2

from ansible_base.authentication.authenticator_configurators.github import GithubTeamConfiguration
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_team')


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubTeamOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubTeamConfiguration
    logger = logger
    type = "github-team"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
