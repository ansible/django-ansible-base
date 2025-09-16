import logging
from copy import deepcopy

from django.utils.translation import gettext_lazy as _
from social_core.backends.azuread import AzureADOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin
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
        required=False,
    )

    KEY = CharField(
        help_text=_("The Client ID (OIDC Key) from Azure AD. Will also be used as the 'audience' for JWT decoding."),
        allow_null=False,
        ui_field_label=_('Client ID'),
    )

    SECRET = CharField(
        help_text=_("'The Client Secret (OIDC Secret) from Azure AD."),
        allow_null=True,
        ui_field_label=_('Secret'),
    )

    GROUPS_CLAIM = CharField(
        help_text=_("The JSON key used to extract the user's groups from the ID token or userinfo endpoint."),
        required=False,
        allow_null=False,
        default="groups",
        ui_field_label=_("Groups Claim"),
    )

    USERNAME_FIELD = CharField(
        help_text=_(
            "The name of the field to use as the username. "
            "This field can be in: the assertion, the id token or the standard user info. "
            "If not available this will default to the username."
        ),
        required=False,
        allow_null=True,
        ui_field_label=_("Field to use as username"),
    )


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, AzureADOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = AzureADConfiguration
    type = "azuread"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SECRET']

    @property
    def groups_claim(self):
        return self.setting('GROUPS_CLAIM')

    def get_user_groups(self, extra_groups=[]):
        return extra_groups

    def get_user_details(self, response):
        """
        Return user details from Azure AD account

        This method is an override from social-core/social_core/backends/azuread.py
        It allows us to control what the username is.
        """
        # start with the assertion we got back
        user_details = deepcopy(response)
        # At this point the response has not been overlaid with the info in the id token
        # so we need to get the info from the id token and overlay it
        if 'access_token' in response and 'id_token' in response:
            user_details.update(self.user_data(response['access_token'], response=response))
        # Finally overlay the fields from what we want to return initially
        return_object = super().get_user_details(response)
        user_details.update(return_object)

        if self.setting("USERNAME_FIELD"):
            alternate_username = user_details.get(self.setting("USERNAME_FIELD"))
            if alternate_username:
                return_object['username'] = alternate_username
            else:
                valid_keys = list(user_details.keys())
                valid_keys.sort()
                logger.warning(
                    f"Username field '{self.setting('USERNAME_FIELD')}' not found in AD response, using default username of {return_object['username']}."
                )
                logger.warning(f"Valid keys are: {valid_keys}")
        return return_object
