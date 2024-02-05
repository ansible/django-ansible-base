import logging

from social_core.backends.github import GithubOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.local')


class GithubConfiguration(BaseAuthenticatorConfiguration):
    documenation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/github.html"

    CALLBACK_URL = URLField(
        help_text=(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        default='https://localhost/api/gateway/social/complete/',
        allow_null=False,
        ui_field_label=('Callback URL'),
    )

    KEY = CharField(
        help_text=('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=('GitHub OAuth2 Key'),
    )

    SECRET = CharField(
        help_text=('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=('GitHub OAuth2 Secret'),
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubConfiguration
    logger = logger
    type = "github"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
