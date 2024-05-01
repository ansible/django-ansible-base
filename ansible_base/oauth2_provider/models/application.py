import re

import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models.common import NamedCommonModel

activitystream = object
if 'ansible_base.activitystream' in settings.INSTALLED_APPS:
    from ansible_base.activitystream.models import AuditableModel

    activitystream = AuditableModel


DATA_URI_RE = re.compile(r'.*')  # FIXME


class OAuth2Application(oauth2_models.AbstractApplication, NamedCommonModel, activitystream):
    router_basename = 'application'
    ignore_relations = ['oauth2idtoken', 'grant', 'oauth2refreshtoken']
    # We do NOT add client_secret to encrypted_fields because it is hashed by Django OAuth Toolkit
    # and it would end up hashing the encrypted value.

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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="applications",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
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
    # Not overriding client_secret... Details:
    # It would be nice to just use our usual encrypted_fields flow here
    # until DOT makes a release with https://github.com/jazzband/django-oauth-toolkit/pull/1311
    # there is no way to disable its expectation of using its own hashing
    # (which is Django's make_password/check_password).
    # So we use their field here.
    # Previous versions of DOT didn't hash the field at all and AWX pins
    # to <2.0.0 so AWX used the AWX encryption with no issue.
    client_type = models.CharField(
        max_length=32, choices=CLIENT_TYPES, help_text=_('Set to Public or Confidential depending on how secure the client device is.')
    )
    skip_authorization = models.BooleanField(default=False, help_text=_('Set True to skip authorization step for completely trusted applications.'))
    authorization_grant_type = models.CharField(
        max_length=32, choices=GRANT_TYPES, help_text=_('The Grant type the user must use for acquire tokens for this application.')
    )
    created = None  # Tracked in CommonModel, no need for this
    updated = None  # Tracked in CommonModel, no need for this

    def get_absolute_url(self):
        # This is kind of annoying. This method lives on the superclass and we check for it in CommonModel.
        # But better would be to not have this method and let the CommonModel logic fall back to the "right" way of finding this.
        return reverse(f'{self.router_basename}-detail', kwargs={'pk': self.pk})
