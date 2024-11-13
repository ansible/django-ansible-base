import hashlib

import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from oauthlib import oauth2

from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.utils.hashing import hash_string
from ansible_base.lib.utils.models import prevent_search
from ansible_base.lib.utils.settings import get_setting
from ansible_base.oauth2_provider.utils import is_external_account

SCOPES = ['read', 'write']


def validate_scope(value):
    given_scopes = value.split(' ')
    if not given_scopes:
        raise ValidationError(_('Scope must be a simple space-separated string with allowed scopes: %(scopes)s') % {'scopes': ', '.join(SCOPES)})
    for scope in given_scopes:
        if scope not in SCOPES:
            raise ValidationError(_('Invalid scope: %(scope)s. Must be one of: %(scopes)s') % {'scope': scope, 'scopes': ', '.join(SCOPES)})


activitystream = object
if 'ansible_base.activitystream' in settings.INSTALLED_APPS:
    from ansible_base.activitystream.models import AuditableModel

    activitystream = AuditableModel


class OAuth2AccessToken(CommonModel, oauth2_models.AbstractAccessToken, activitystream):
    router_basename = 'token'
    ignore_relations = ['refresh_token']
    activity_stream_excluded_field_names = ['last_used']

    class Meta(oauth2_models.AbstractAccessToken.Meta):
        verbose_name = _('access token')
        ordering = ('id',)
        swappable = "OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="access_tokens",
        help_text=_('The user representing the token owner.'),
    )
    # Overriding to set related_name
    application = models.ForeignKey(
        settings.OAUTH2_PROVIDER_APPLICATION_MODEL,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='access_tokens',
        help_text=_('The related application. If None, this is a user token instead of an application token.'),
    )
    description = models.TextField(default='', blank=True, help_text=_('A description for this token.'))
    last_used = models.DateTimeField(null=True, default=None, editable=False, help_text=_('A timestamp of when this token was last used.'))
    scope = models.CharField(
        default='write',
        max_length=32,
        help_text=_("Allowed scopes, further restricts user permissions. Must be a simple space-separated string with allowed scopes ['read', 'write']."),
        validators=[validate_scope],
    )
    token = prevent_search(models.CharField(max_length=255, unique=True, help_text=_("The generated token value.")))
    updated = None  # Tracked in CommonModel with 'modified', no need for this

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
                    _('OAuth2 Tokens cannot be created by users associated with an external authentication provider (%(authenticator)s)')
                    % {'authenticator': external_account.name}
                )

    def save(self, *args, **kwargs):
        if not self.pk:
            self.validate_external_users()
            self.token = hash_string(self.token, hasher=hashlib.sha256, algo="sha256")
        super().save(*args, **kwargs)
