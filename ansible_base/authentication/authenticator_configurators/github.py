from django.utils.translation import gettext_lazy as _

from ansible_base.authentication.authenticator_plugins.base import BaseAuthenticatorConfiguration
from ansible_base.lib.serializers.fields import CharField, ListField, URLField


class GithubConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        allow_null=False,
        required=False,
        ui_field_label=_('Github Oauth2 Callback URL'),
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
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html#github-for-organizations"

    SCOPE = ListField(
        help_text=_('The authorization scope for users. Defaults to "read:org".'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Scope'),
        default=['read:org'],
    )

    NAME = CharField(
        help_text=_('The OAuth2 organization name.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Organization Name'),
    )


class GithubTeamConfiguration(GithubConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html#github-for-teams"

    SCOPE = ListField(
        help_text=_('The authorization scope for users. Defaults to "read:org".'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Scope'),
        default=['read:org'],
    )

    ID = CharField(
        help_text=_('The OAuth2 team ID.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Team ID'),
    )


###############################################################################
#   ENTERPRISE
###############################################################################


class GithubEnterpriseConfiguration(GithubConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github_enterprise.html"

    URL = URLField(
        help_text=_('The base url for the GithHub enterprise instance.'),
        allow_null=False,
        ui_field_label=_('Base URL'),
    )

    API_URL = URLField(
        help_text=_('The base url for the GithHub enterprise instance.'),
        allow_null=False,
        ui_field_label=_('Github OAuth2 Enterprise API URL'),
    )


class GithubEnterpriseOrgConfiguration(GithubEnterpriseConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github_enterprise.html#github-enterprise-for-organizations"

    NAME = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 Enterprise Org Name'),
    )


class GithubEnterpriseTeamConfiguration(GithubEnterpriseConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github_enterprise.html#github-enterprise-for-teams"

    ID = CharField(
        help_text=_('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=_('GitHub OAuth2 team ID'),
    )
