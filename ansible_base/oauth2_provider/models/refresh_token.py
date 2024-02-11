import oauth2_provider.models as oauth2_models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models.common import CommonModel


class OAuth2RefreshToken(oauth2_models.AbstractRefreshToken, CommonModel):
    class Meta(oauth2_models.AbstractRefreshToken.Meta):
        verbose_name = _('access token')
        ordering = ('id',)
        swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"
