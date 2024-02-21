import logging

from social_core.backends.github import GithubOrganizationOAuth2

from ansible_base.authentication.authenticator_configurators.github import GithubOrganizationConfiguration
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_organization')


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubOrganizationOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubOrganizationConfiguration
    logger = logger
    type = "github-org"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
