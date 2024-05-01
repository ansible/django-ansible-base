import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models.common import CommonModel

activitystream = object
if 'ansible_base.activitystream' in settings.INSTALLED_APPS:
    from ansible_base.activitystream.models import AuditableModel

    activitystream = AuditableModel


class OAuth2IDToken(oauth2_models.AbstractIDToken, CommonModel, activitystream):
    class Meta(oauth2_models.AbstractIDToken.Meta):
        verbose_name = _('id token')
        swappable = "OAUTH2_PROVIDER_ID_TOKEN_MODEL"

    created = None  # Tracked in CommonModel, no need for this
    updated = None  # Tracked in CommonModel, no need for this
