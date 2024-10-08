import logging

from django.utils.translation import gettext_lazy as _
from social_core.backends.google import GoogleOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
from ansible_base.lib.serializers.fields import BooleanField, CharField, ChoiceField, ListField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.google_oauth2')


class GoogleOAuth2Configuration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/google.html#google-oauth2"

    #################################
    # Minimal params
    #################################

    KEY = CharField(
        help_text=_("The OAuth2 key from your web application."),
        allow_null=False,
        ui_field_label=_('Google OAuth2 Key'),
    )

    SECRET = CharField(
        help_text=_("The OAuth2 secret from your web application."),
        allow_null=True,
        ui_field_label=_('Google OAuth2 Secret'),
    )

    #################################
    # Additional params
    #################################

    CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your application as part of your registration process. Refer to the documentation for more detail.'
        ),
        required=False,
        allow_null=True,
        ui_field_label=_("Callback URL"),
    )

    ACCESS_TOKEN_URL = URLField(
        help_text=_("The URL to obtain an access token from the OIDC provider."),
        required=False,
        allow_null=True,
        ui_field_label=_("Access Token URL"),
    )

    ACCESS_TOKEN_METHOD = ChoiceField(
        help_text=_("The HTTP method to be used when requesting an access token. Typically 'POST' or 'GET'."),
        default="POST",
        allow_null=True,
        required=False,
        choices=['GET', 'PUT', 'POST', 'PATCH', 'DELETE'],
        ui_field_label=_("Access Token Method"),
    )

    AUTHORIZATION_URL = URLField(
        help_text=_("The URL to redirect the user for Google OAuth2  provider authorization."),
        required=False,
        allow_null=True,
        ui_field_label=_("Authorization URL"),
    )

    REDIRECT_STATE = BooleanField(
        help_text=_("Enable or disable state parameter in the redirect URI. Recommended to be True for preventing CSRF attacks."),
        default=False,
        allow_null=True,
        ui_field_label=_("Redirect State"),
    )

    REVOKE_TOKEN_METHOD = ChoiceField(
        help_text=_("The HTTP method to be used when revoking an access token. Typically 'POST' or 'GET'."),
        default="GET",
        allow_null=True,
        choices=['GET', 'PUT', 'POST', 'PATCH', 'DELETE'],
        ui_field_label=_("Revoke Token Method"),
    )

    REVOKE_TOKEN_URL = URLField(
        help_text=_("The URL to revoke tokens. Used in the token revocation flow."),
        required=False,
        allow_null=True,
        ui_field_label=_("Revoke Token URL"),
    )

    SCOPE = ListField(
        help_text=_('The authorization scope for users. Defaults to ["openid", "email", "profile"].'),
        required=False,
        allow_null=False,
        ui_field_label=_('List of OAuth2 Scope(s)'),
        default=["openid", "email", "profile"],
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GoogleOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GoogleOAuth2Configuration
    type = "google_oauth2"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
