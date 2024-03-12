import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.azuread import AzureADOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.azuread')


class AzureADConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/azuread.html"

    #################################
    # Minimal params
    #################################

    CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail. '
        ),
        ui_field_label=_('Azure AD OAuth2 Callback URL'),
    )

    KEY = CharField(
        help_text=_("The OIDC key (Client ID) from your IDP. Will also be used as the 'audience' for JWT decoding."),
        allow_null=False,
        ui_field_label=_('OIDC Key'),
    )

    SECRET = CharField(
        help_text=_("'The OIDC secret (Client Secret) from your IDP."),
        allow_null=True,
        ui_field_label=_('OIDC Secret'),
    )


class AuthenticatorPlugin(SocialAuthMixin, AzureADOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = AzureADConfiguration
    type = "azuread"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
