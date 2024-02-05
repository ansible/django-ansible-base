import logging

from rest_framework.reverse import reverse
from social_core.backends.github import GithubOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.authenticator_plugins.utils import generate_authenticator_slug
from ansible_base.authentication.social_auth import SocialAuthMixin
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


class AuthenticatorPlugin(SocialAuthMixin, GithubOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubConfiguration
    logger = logger
    type = "github"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']

    def validate(self, serializer, data):
        # if we have an instance already and we didn't get a configuration parameter we are just updating other fields and can return
        if serializer.instance and 'configuration' not in data:
            return data

        configuration = data['configuration']
        if not configuration.get('CALLBACK_URL', None):
            if not serializer.instance:
                slug = generate_authenticator_slug(data['type'], data['name'])
            else:
                slug = serializer.instance.slug

            configuration['CALLBACK_URL'] = reverse('social:complete', request=serializer.context['request'], kwargs={'backend': slug})

        return data
