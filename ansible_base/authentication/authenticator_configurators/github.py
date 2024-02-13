from django.utils.translation import gettext_lazy as _

from ansible_base.authentication.authenticator_plugins.base import BaseAuthenticatorConfiguration
from ansible_base.lib.serializers.fields import CharField, ListField, URLField


class GithubConfiguration(BaseAuthenticatorConfiguration):

    documenation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        allow_null=False,
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


class GithubOrganizationConfiguration(GithubConfiguration):

    # SOCIAL_AUTH_GITHUB_SCOPE = ['read:org']
    SCOPE = ListField(
        help_text=_('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Secret'),
        default=['read:org'],
    )

    NAME = CharField(
        help_text=_('The organization name.'),
        allow_null=False,
        ui_field_label=_('GitHub org name'),
    )


class GithubTeamConfiguration(GithubConfiguration):

    # SOCIAL_AUTH_GITHUB_SCOPE = ['read:org']
    SCOPE = ListField(
        help_text=_('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Secret'),
        default=['read:org'],
    )

    ID = CharField(
        help_text=_('The github team ID.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Key'),
    )


###############################################################################
#   ENTERPRISE
###############################################################################


class GithubEnterpriseConfiguration(GithubConfiguration):

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


class GithubEnterpriseOrgConfiguration(GithubEnterpriseConfiguration):
    documenation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    NAME = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub enterprise org name'),
    )


class GithubEnterpriseTeamConfiguration(GithubEnterpriseConfiguration):
    documenation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    ID = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Key'),
    )
