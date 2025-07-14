import logging

from social_core.backends.github_enterprise import GithubEnterpriseOrganizationOAuth2

from ansible_base.authentication.authenticator_configurators.github import GithubEnterpriseOrgConfiguration
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_enterprise_organization')


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubEnterpriseOrganizationOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubEnterpriseOrgConfiguration
    logger = logger
    type = "github-enterprise-org"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
