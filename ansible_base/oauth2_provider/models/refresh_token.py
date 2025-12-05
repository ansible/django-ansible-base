import hashlib
import logging

import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.logging import log_auth_event
from ansible_base.lib.utils.hashing import hash_string
from ansible_base.lib.utils.models import prevent_search

logger = logging.getLogger('ansible_base.oauth2_provider.models.refresh_token')

activitystream = object
if 'ansible_base.activitystream' in settings.INSTALLED_APPS:
    from ansible_base.activitystream.models import AuditableModel

    activitystream = AuditableModel


class OAuth2RefreshToken(CommonModel, oauth2_models.AbstractRefreshToken, activitystream):
    class Meta(oauth2_models.AbstractRefreshToken.Meta):
        verbose_name = _('refresh token')
        ordering = ('id',)
        swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"

    token = prevent_search(models.CharField(max_length=255, help_text=_("The refresh token value.")))
    updated = None  # Tracked in CommonModel with 'modified', no need for this

    def save(self, *args, **kwargs):
        create_token = not bool(self.pk)
        if create_token:
            self.token = hash_string(self.token, hasher=hashlib.sha256, algo="sha256")
        super().save(*args, **kwargs)
        access_token_id = self.access_token.pk if hasattr(self, 'access_token') and self.access_token else "N/A"
        user_name = self.user.username if self.user else "N/A"
        if create_token:
            log_auth_event(f"Created OAuth2 refresh token {self.pk} for user '{user_name}' linked to access token {access_token_id}", second_logger=logger)
        else:
            log_auth_event(f"Modified OAuth2 refresh token {self.pk} for user '{user_name}' linked to access token {access_token_id}", second_logger=logger)
