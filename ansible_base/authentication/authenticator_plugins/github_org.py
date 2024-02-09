import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.github import GithubOrganizationOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import CharField, SocialOrganizationMapField, SocialTeamMapField, URLField, ListField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_organization')


class GithubOrganizationConfiguration(BaseAuthenticatorConfiguration):
    CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        allow_null=False,
        default='',
        ui_field_label=_('Callback URL'),
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

    # SOCIAL_AUTH_GITHUB_SCOPE = ['read:org']
    SCOPE = ListField(
        help_text=_('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Secret'),
        default=['read:org']
    )

    NAME = CharField(
        help_text=_('The organization name.'),
        allow_null=False,
        ui_field_label=_('GitHub org name'),
    )

    ORGANIZATION_MAP = SocialOrganizationMapField(
        help_text=_('The organization map.'),
        allow_null=False,
        ui_field_label=_('GitHub org map'),
    )

    ORGANIZATION_TEAM_MAP = SocialTeamMapField(
        help_text=_('The organization team map.'),
        allow_null=False,
        ui_field_label=_('GitHub org team map'),
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubOrganizationOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubOrganizationConfiguration
    logger = logger
    type = "github-org"
    category = "sso"
    configuration_encrypted_fields = ['ORG_SECRET']
