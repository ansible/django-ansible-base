import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.github import GithubTeamOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_team')


class GithubTeamConfiguration(BaseAuthenticatorConfiguration):
    documenation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    TEAM_CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        allow_null=False,
        ui_field_label=_('Callback URL'),
    )

    TEAM_KEY = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Key'),
    )

    TEAM_SECRET = CharField(
        help_text=_('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Secret'),
    )

    TEAM_ID = CharField(
        help_text=_('The github team ID.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Key'),
    )

    TEAM_ORGANIZATION_MAP = CharField(
        help_text=_('The github team ID.'),
        allow_null=False,
        ui_field_label=_('GitHub team organization map'),
    )

    TEAM_TEAM_MAP = CharField(
        help_text=_('The github team ID.'),
        allow_null=False,
        ui_field_label=_('GitHub team organization map'),
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubTeamOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubTeamConfiguration
    logger = logger
    type = "github-team"
    category = "sso"
    configuration_encrypted_fields = ['TEAM_SECRET']
