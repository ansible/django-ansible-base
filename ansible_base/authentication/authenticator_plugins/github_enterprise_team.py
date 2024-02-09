import logging

from social_core.backends.github_enterprise import GithubEnterpriseTeamOAuth2

from ansible_base.authentication.authenticator_configurators.github import GithubEnterpriseTeamConfiguration
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_enterprise_team')


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubEnterpriseTeamOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubEnterpriseTeamConfiguration
    logger = logger
    type = "github-enterprise-team"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
