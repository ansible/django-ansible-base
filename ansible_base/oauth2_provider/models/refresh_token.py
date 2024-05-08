import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.utils.models import prevent_search

activitystream = object
if 'ansible_base.activitystream' in settings.INSTALLED_APPS:
    from ansible_base.activitystream.models import AuditableModel

    activitystream = AuditableModel


class OAuth2RefreshToken(CommonModel, oauth2_models.AbstractRefreshToken, activitystream):
    class Meta(oauth2_models.AbstractRefreshToken.Meta):
        verbose_name = _('refresh token')
        ordering = ('id',)
        swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"

    token = prevent_search(models.CharField(max_length=255))
    updated = None  # Tracked in CommonModel with 'modified', no need for this
