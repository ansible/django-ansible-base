import re

import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from oauth2_provider.generators import generate_client_secret

from ansible_base.lib.abstract_models.common import NamedCommonModel

DATA_URI_RE = re.compile(r'.*')  # FIXME


class OAuth2Application(oauth2_models.AbstractApplication, NamedCommonModel):
    router_basename = 'application'
    ignore_relations = ['oauth2idtoken', 'grant', 'oauth2refreshtoken']
    encrypted_fields = ['client_secret']

    class Meta(oauth2_models.AbstractAccessToken.Meta):
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
        getattr(settings, 'ANSIBLE_BASE_ORGANIZATION_MODEL'),
        related_name='applications',
        help_text=_('Organization containing this application.'),
        on_delete=models.CASCADE,
        null=True,
    )
    client_secret = models.CharField(
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

    def get_absolute_url(self):
        # This is kind of annoying. This method lives on the superclass and we check for it in CommonModel.
        # But better would be to not have this method and let the CommonModel logic fall back to the "right" way of finding this.
        return reverse(f'{self.router_basename}-detail', kwargs={'pk': self.pk})
