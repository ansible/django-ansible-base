import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.github_enterprise import GithubEnterpriseOrganizationOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_enterprise_organization')


class GithubEnterpriseOrgConfiguration(BaseAuthenticatorConfiguration):
    documenation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    ENTERPRISE_ORG_CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        allow_null=False,
        ui_field_label=_('Callback URL'),
    )

    ENTERPRISE_ORG_URL = URLField(
        help_text=_(
            'The base url for the GithHb enterprise instance.'
        ),
        allow_null=False,
        ui_field_label=_('Base URL'),
    )

    ENTERPRISE_ORG_API_URL = URLField(
        help_text=_(
            'The base url for the GithHb enterprise instance.'
        ),
        allow_null=False,
        ui_field_label=_('API URL'),
    )

    ENTERPRISE_ORG_KEY = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Key'),
    )

    ENTERPRISE_ORG_SECRET = CharField(
        help_text=_('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Secret'),
    )

    ENTERPRISE_ORG_NAME = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub enterprise org name'),
    )

    ENTERPRISE_ORG_ORGANIZATION_MAP = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub enterprise org org map'),
    )

    ENTERPRISE_ORG_TEAM_MAP = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub enterprise org team map'),
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubEnterpriseOrganizationOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubEnterpriseOrgConfiguration
    logger = logger
    type = "github-enterprise-org"
    category = "sso"
    configuration_encrypted_fields = ['ENTERPRISE_ORG_SECRET']
