import logging
from dataclasses import dataclass
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from ansible_base.authentication.authenticator_plugins._radiusauth import RADIUSBackend as _RADIUSBackend
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.utils.authentication import get_or_create_authenticator_user
from ansible_base.authentication.utils.claims import update_user_claims
from ansible_base.lib.serializers.fields import CharField, IntegerField

logger = logging.getLogger(__name__)

User = get_user_model()


@dataclass
class RADIUSUser:
    username: str
    groups: list[str]
    is_staff: bool
    is_superuser: bool


class RADIUSBackend(_RADIUSBackend):
    def get_django_user(self, username, password=None, groups=None, is_staff=False, is_superuser=False):
        return RADIUSUser(
            username=username,
            groups=groups or [],
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    def get_user_groups(self, group_names):
        return group_names


class RADIUSConfiguration(BaseAuthenticatorConfiguration):
    SERVER = CharField(
        label=_("RADIUS Server"),
        help_text="Hostname of RADIUS server.",
        ui_field_label=_('Hostname of RADIUS Server'),
        required=True,
    )

    PORT = IntegerField(
        min_value=1,
        max_value=65535,
        default=1812,
        label=_("RADIUS Port"),
        help_text=_("Port number of RADIUS server."),
        ui_field_label=_("Port number of RADIUS Server"),
    )

    SECRET = CharField(
        label=_("RADIUS Secret"),
        help_text=_("Shared secret for authenticating to RADIUS server."),
        ui_field_label=_("Shared secret for authenticating to RADIUS server."),
        required=True,
    )


class AuthenticatorPlugin(AbstractAuthenticatorPlugin):
    configuration_class = RADIUSConfiguration
    type = "RADIUS"
    category = "password"
    configuration_encrypted_fields = ["SECRET"]

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)
        self.set_logger(logger)

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        settings = SimpleNamespace(
            RADIUS_SERVER=self.settings["SERVER"],
            RADIUS_PORT=self.settings["PORT"],
            RADIUS_SECRET=self.settings["SECRET"],
        )
        backend = RADIUSBackend(settings)
        radius_user = backend.authenticate(request, username, password)
        if radius_user is None:
            return None

        user, _authenticator_user, _is_created = get_or_create_authenticator_user(
            username,
            authenticator=self.database_instance,
            user_details={},
            extra_data={"username": username},
        )
        return update_user_claims(user, self.database_instance, radius_user.groups)
