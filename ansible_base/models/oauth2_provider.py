import logging
import re

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import connection, models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from ansible_base.models.common import CommonModel, NamedCommonModel
from ansible_base.utils.authentication import is_external_account
from ansible_base.utils.encryption import ansible_encryption
from ansible_base.utils.features import OAUTH2_PROVIDER, feature_enabled
from ansible_base.utils.oauth2_provider import generate_client_id, generate_client_secret
from ansible_base.utils.settings import get_setting

DATA_URI_RE = re.compile(r'.*')  # FIXME

logger = logging.getLogger('ansible_base.models.oauth')

#
# There were a lot of problems making the initial migrations for this class
# See https://github.com/jazzband/django-oauth-toolkit/issues/634 which helped
#
# Here were my steps:
#  1. Start the server
#  2. Set all values in settings.py in the main app
#  3. Set ANSIBLE_BASE_FEATURES.OAUTH2_PROVIDER as True
#  3. Comment out all OAUTH2_PROVIDER_* settings in dynamic_settings.py
#  4. Change all classes in here to remove oauth2_models.Abstract* as superclasses (including the meta ones)
#  5. gateway-manage makemigrations && gateway-manage migrate ansible_base
#  6. Uncomment all OAUTH2_PROVIDER_* settings
#  7. Revert step 4
#  8. gateway-manage makemigrations && gateway-manage migrate ansible_base
#       When you do this django does not realize that you are creating an initial migration and tell you its impossible to migrate so fields
#       It will ask you to either: 1. Enter a default 2. Quit
#       Tell it to use the default if it has one populated at the prompt. Other wise use django.utils.timezone.now for timestamps and  '' for other items
#       This wont matter for us because there will be no data in the tables between these two migrations
#


class OAuth2ClientSecretField(models.CharField):
    def get_db_prep_value(self, value, connection, prepared=False):
        return super().get_db_prep_value(ansible_encryption.encrypt_string(value), connection, prepared)

    def from_db_value(self, value, expression, connection):
        if value and value.startswith('$encrypted$'):
            return ansible_encryption.decrypt_string(value)
        return value


if feature_enabled(OAUTH2_PROVIDER):
    # Only import this code if the feature is enabled.
    # The DB will still have the tables built from the migration
    # But we will get errors if we try to import the oauth2_provider classes if the application is not installed

    import oauth2_provider.models as oauth2_models
    from oauthlib import oauth2

    class OAuth2Application(oauth2_models.AbstractApplication, NamedCommonModel):
        reverse_name_override = 'application'

        class Meta(oauth2_models.AbstractAccessToken.Meta):
            app_label = 'ansible_base'
            verbose_name = _('application')
            unique_together = (("name", "organization"),)
            ordering = ('organization', 'name')
            swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"

        CLIENT_TYPES = (
            ("confidential", _("Confidential")),
            ("public", _("Public")),
        )

        GRANT_TYPES = (
            ("authorization-code", _("Authorization code")),
            ("password", _("Resource owner password-based")),
        )

        # Here we are going to overwrite this from the parent class so that we can change the default
        client_id = models.CharField(db_index=True, default=generate_client_id, max_length=100, unique=True)
        description = models.TextField(
            default='',
            blank=True,
        )
        logo_data = models.TextField(
            default='',
            editable=False,
            validators=[RegexValidator(DATA_URI_RE)],
        )
        organization = models.ForeignKey(
            getattr(settings, 'ANSIBLE_BASE_ORGANIZATION_MODEL', 'Organization'),
            related_name='applications',
            help_text=_('Organization containing this application.'),
            on_delete=models.CASCADE,
            null=True,
        )
        client_secret = OAuth2ClientSecretField(
            max_length=1024,
            blank=True,
            default=generate_client_secret,
            db_index=True,
            help_text=_('Used for more stringent verification of access to an application when creating a token.'),
        )
        client_type = models.CharField(
            max_length=32, choices=CLIENT_TYPES, help_text=_('Set to Public or Confidential depending on how secure the client device is.')
        )
        skip_authorization = models.BooleanField(default=False, help_text=_('Set True to skip authorization step for completely trusted applications.'))
        authorization_grant_type = models.CharField(
            max_length=32, choices=GRANT_TYPES, help_text=_('The Grant type the user must use for acquire tokens for this application.')
        )

    class OAuth2IDToken(oauth2_models.AbstractIDToken, CommonModel):
        class Meta(oauth2_models.AbstractIDToken.Meta):
            app_label = 'ansible_base'
            verbose_name = _('id token')
            swappable = "OAUTH2_PROVIDER_ID_TOKEN_MODEL"

    class OAuth2AccessToken(oauth2_models.AbstractAccessToken, CommonModel):
        reverse_name_override = 'token'
        # There is a special condition where, as the user is logging in we want to update the last_used field.
        # However, this happens before the user is set for the request.
        # If this is the only field attempting to be saved, don't update the modified on/by fields
        not_user_modified_fields = ['last_used']

        class Meta(oauth2_models.AbstractAccessToken.Meta):
            app_label = 'ansible_base'
            verbose_name = _('access token')
            ordering = ('id',)
            swappable = "OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL"

        user = models.ForeignKey(
            settings.AUTH_USER_MODEL,
            on_delete=models.CASCADE,
            blank=True,
            null=True,
            related_name="%(app_label)s_%(class)s",
            help_text=_('The user representing the token owner'),
        )
        description = models.TextField(
            default='',
            blank=True,
        )
        last_used = models.DateTimeField(
            null=True,
            default=None,
            editable=False,
        )
        scope = models.CharField(
            blank=True,
            default='write',
            max_length=32,
            choices=[('read', 'read'), ('write', 'write')],
            help_text=_("Allowed scopes, further restricts user's permissions. Must be a simple space-separated string with allowed scopes ['read', 'write']."),
        )

        def is_valid(self, scopes=None):
            valid = super(OAuth2AccessToken, self).is_valid(scopes)
            if valid:
                self.last_used = now()

                def _update_last_used():
                    if OAuth2AccessToken.objects.filter(pk=self.pk).exists():
                        self.save(update_fields=['last_used'])

                connection.on_commit(_update_last_used)
            return valid

        def validate_external_users(self):
            if self.user and get_setting('ALLOW_OAUTH2_FOR_EXTERNAL_USERS') is False:
                external_account = is_external_account(self.user)
                if external_account:
                    raise oauth2.AccessDeniedError(
                        _('OAuth2 Tokens cannot be created by users associated with an external authentication provider ({})').format(external_account)
                    )

        def save(self, *args, **kwargs):
            if not self.pk:
                self.validate_external_users()
            super().save(*args, **kwargs)

    class OAuth2RefreshToken(oauth2_models.AbstractRefreshToken, CommonModel):
        class Meta(oauth2_models.AbstractRefreshToken.Meta):
            app_label = 'ansible_base'
            verbose_name = _('access token')
            ordering = ('id',)
            swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"
