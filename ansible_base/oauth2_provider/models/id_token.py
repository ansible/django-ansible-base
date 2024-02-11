import oauth2_provider.models as oauth2_models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models.common import CommonModel


class OAuth2IDToken(oauth2_models.AbstractIDToken, CommonModel):
    class Meta(oauth2_models.AbstractIDToken.Meta):
        verbose_name = _('id token')
        swappable = "OAUTH2_PROVIDER_ID_TOKEN_MODEL"
