import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.db import connection, models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from oauthlib import oauth2

from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.utils.settings import get_setting
from ansible_base.oauth2_provider.utils import is_external_account


class OAuth2AccessToken(oauth2_models.AbstractAccessToken, CommonModel):
    reverse_name_override = 'token'
    # There is a special condition where, as the user is logging in we want to update the last_used field.
    # However, this happens before the user is set for the request.
    # If this is the only field attempting to be saved, don't update the modified on/by fields
    not_user_modified_fields = ['last_used']

    class Meta(oauth2_models.AbstractAccessToken.Meta):
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
