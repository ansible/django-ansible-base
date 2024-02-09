import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.github_enterprise import GithubEnterpriseTeamOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_enterprise_team')


class GithubEnterpriseTeamConfiguration(BaseAuthenticatorConfiguration):
    documenation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        allow_null=False,
        ui_field_label=_('Callback URL'),
    )

    URL = URLField(
        help_text=_('The base url for the GithHb enterprise instance.'),
        allow_null=False,
        ui_field_label=_('Base URL'),
    )

    API_URL = URLField(
        help_text=_('The base url for the GithHb enterprise instance.'),
        allow_null=False,
        ui_field_label=_('API URL'),
    )

    KEY = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Key'),
    )

    SECRET = CharField(
        help_text=_('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Secret'),
    )

    ID = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Key'),
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubEnterpriseTeamOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubEnterpriseTeamConfiguration
    logger = logger
    type = "github-enterprise-team"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
