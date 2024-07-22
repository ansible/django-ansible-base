import logging

from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from tacacs_plus.client import TACACSClient
from tacacs_plus.flags import TAC_PLUS_AUTHEN_TYPES, TAC_PLUS_VIRTUAL_REM_ADDR

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.authentication.utils.authentication import get_or_create_authenticator_user
from ansible_base.authentication.utils.claims import update_user_claims
from ansible_base.lib.serializers.fields import BooleanField, CharField, ChoiceField, IntegerField
from ansible_base.lib.utils.requests import get_remote_host

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.tacacs')

#
# Someone created a django library for tacacs: https://github.com/mwallraf/django-auth-tacacs
# It's appears to leverage tacacs-plus but has a single maintainer and has not been touched in a year.
# There are no issues on the repo but there has only been one release.
# The library is farily minimal so for now we are just going to do our own coding in this authenticator.
# Later on, if we choose, it should be a simple lift to use django-auth-tacacs
#


def validate_tacacsplus_disallow_nonascii(value):
    try:
        value.encode('ascii')
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        raise ValidationError(_('TACACS+ secret does not allow non-ascii characters'))


class TacacsConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://github.com/ansible/tacacs_plus"
    HOST = CharField(
        label="TACACS+ Server",
        required=True,
        help_text="Hostname of TACACS+ server.",
        ui_field_label=_('Hostname of TACACS+ Server'),
    )
    PORT = IntegerField(
        min_value=1,
        max_value=65535,
        default=49,
        label=_('TACACS+ Port'),
        help_text=_('Port number of TACACS+ server.'),
        ui_field_label=_('Port number of TACACS+ Server'),
    )
    AUTH_PROTOCOL = ChoiceField(
        choices=['ascii', 'pap', 'chap'],
        default='ascii',
        label=_('TACACS+ Authentication Protocol'),
        help_text=_('Choose the authentication protocol used by TACACS+ client.'),
        ui_field_label=_('TACACS+ Authentication Protocol'),
    )
    REM_ADDR = BooleanField(
        default=True,
        label=_('TACACS+ client address sending enabled'),
        help_text=_('Enable the client address sending by TACACS+ client.'),
        ui_field_label=_('TACACS+ client address sending enabled'),
    )
    SECRET = CharField(
        validators=[validate_tacacsplus_disallow_nonascii],
        label=_('TACACS+ Secret'),
        help_text=_('Shared secret for authenticating to TACACS+ server.'),
        ui_field_label=_('Shared secret for authenticating to TACACS+ server.'),
        required=True,
    )
    SESSION_TIMEOUT = IntegerField(
        min_value=0,
        default=5,
        label=_('TACACS+ Auth Session Timeout'),
        help_text=_('TACACS+ session timeout value in seconds, 0 disables timeout.'),
        ui_field_label=_('TACACS+ Auth Session Timeout'),
    )


class AuthenticatorPlugin(SocialAuthMixin, AbstractAuthenticatorPlugin, ModelBackend):
    configuration_class = TacacsConfiguration
    logger = logger
    type = "tacacs"
    category = "password"

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)
        self.configuration_encrypted_fields = ['SECRET']

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        if not self.database_instance:
            logger.error("AuthenticatorPlugin was missing an authenticator")
            return None

        if not self.database_instance.enabled:
            logger.info(f"TACACS authenticator {self.database_instance.name} is disabled, skipping")
            return None

        try:
            tacacs_client = TACACSClient(
                self.database_instance.configuration["HOST"],
                self.database_instance.configuration["PORT"],
                self.database_instance.configuration["SECRET"],
                timeout=self.database_instance.configuration["SESSION_TIMEOUT"],
            )
            rem_addr = TAC_PLUS_VIRTUAL_REM_ADDR
            client_ip = get_remote_host(request)
            if client_ip:
                rem_addr = client_ip

            reply = tacacs_client.authenticate(
                username,
                password,
                authen_type=TAC_PLUS_AUTHEN_TYPES[self.database_instance.configuration['AUTH_PROTOCOL']],
                rem_addr=rem_addr,
            )

            if reply.valid:
                user, _authenticator_user, _created = get_or_create_authenticator_user(
                    username,
                    self.database_instance,
                    user_details={},
                    extra_data={'username': username},
                )

                return update_user_claims(user, self.database_instance, [])
        except Exception as e:
            logger.exception("TACACS+ Authentication Error: %s" % str(e))

        # Tacacs could not validate us so return None.
        return None
