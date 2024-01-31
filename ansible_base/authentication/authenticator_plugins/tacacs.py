import logging

from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# import tacacs_plus

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import CharField, IntegerField, ChoiceField, BooleanField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.tacacs')


def validate_tacacsplus_disallow_nonascii(value):
    try:
        value.encode('ascii')
    except (UnicodeEncodeError, UnicodeDecodeError):
        raise ValidationError(_('TACACS+ secret does not allow non-ascii characters'))


class TacacsConfiguration(BaseAuthenticatorConfiguration):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configuration_encrypted_fields = ['SECRET']

    documentation_url = "https://docs.djangoproject.com/en/4.2/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend"
    # TODO: Change the documentation URL to the correct one for TACACS
    HOST = CharField(
        allow_blank=True,
        default='',
        label="TACACS+ Server",
        required=False,
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
        choices=['ascii', 'pap'],
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
        allow_blank=True,
        default='',
        validators=[validate_tacacsplus_disallow_nonascii],
        label=_('TACACS+ Secret'),
        help_text=_('Shared secret for authenticating to TACACS+ server.'),
        ui_field_label=_('Shared secret for authenticating to TACACS+ server.'),
    )
    SESSION_TIMEOUT = IntegerField(
        min_value=0,
        default=5,
        label=_('TACACS+ Auth Session Timeout'),
        help_text=_('TACACS+ session timeout value in seconds, 0 disables timeout.'),
        ui_field_label=_('TACACS+ Auth Session Timeout'),
    )


class AuthenticatorPlugin(SocialAuthMixin, AbstractAuthenticatorPlugin):
    configuration_class = TacacsConfiguration
    logger = logger
    type = "tacacs"
    category = "password"

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        user = super().authenticate(request, username, password, **kwargs)

        # This auth class doesn't create any new local users, so we just need to make sure
        # it has an AuthenticatorUser associated with it.
        if user:
            AuthenticatorUser.objects.get_or_create(uid=username, user=user, provider=self.database_instance)

        # TODO, we will need to return attributes and claims eventually
        return user


class TACACSPlusBackend(object):
    """
    Custom TACACS+ auth backend for AWX
    """

    def authenticate(self, request, username, password):
        if not self.settings.TACACSPLUS_HOST:
            return None
        try:
            # Upstream TACACS+ client does not accept non-string, so convert if needed.
            tacacs_client = tacacs_plus.TACACSClient(
                django_settings.TACACSPLUS_HOST,
                django_settings.TACACSPLUS_PORT,
                django_settings.TACACSPLUS_SECRET,
                timeout=django_settings.TACACSPLUS_SESSION_TIMEOUT,
            )
            auth_kwargs = {'authen_type': tacacs_plus.TAC_PLUS_AUTHEN_TYPES[django_settings.TACACSPLUS_AUTH_PROTOCOL]}
            if django_settings.TACACSPLUS_AUTH_PROTOCOL:
                client_ip = self._get_client_ip(request)
                if client_ip:
                    auth_kwargs['rem_addr'] = client_ip
            auth = tacacs_client.authenticate(username, password, **auth_kwargs)
        except Exception as e:
            logger.exception("TACACS+ Authentication Error: %s" % str(e))
            return None
        if auth.valid:
            return _get_or_set_enterprise_user(username, password, 'tacacs+')

    def get_user(self, user_id):
        if not django_settings.TACACSPLUS_HOST:
            return None
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    def _get_client_ip(self, request):
        if not request or not hasattr(request, 'META'):
            return None

        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
