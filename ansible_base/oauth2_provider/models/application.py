import oauth2_provider.models as oauth2_models
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from oauth2_provider.generators import generate_client_secret

from ansible_base.lib.abstract_models.common import NamedCommonModel
from ansible_base.lib.utils.models import prevent_search
from ansible_base.lib.utils.response import get_relative_url

activitystream = object
if 'ansible_base.activitystream' in settings.INSTALLED_APPS:
    from ansible_base.activitystream.models import AuditableModel

    activitystream = AuditableModel


class OAuth2Application(NamedCommonModel, oauth2_models.AbstractApplication, activitystream):
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
        help_text=_("The user who created the application."),
    )

    description = models.TextField(
        default='',
        blank=True,
        help_text=_("A description of this application."),
    )
    organization = models.ForeignKey(
        getattr(settings, 'ANSIBLE_BASE_ORGANIZATION_MODEL'),
        related_name='applications',
        help_text=_('Organization containing this application.'),
        on_delete=models.CASCADE,
        null=True,
    )

    app_url = models.URLField(
        default=None,
        blank=True,
        null=True,
        help_text=_("The URL of this application."),
    )

    # It would be nice to just use our usual encrypted_fields flow here
    # until DOT makes a release with https://github.com/jazzband/django-oauth-toolkit/pull/1311
    # there is no way to disable its expectation of using its own hashing
    # (which is Django's make_password/check_password).
    # So we use their field here.
    # Previous versions of DOT didn't hash the field at all and AWX pins
    # to <2.0.0 so AWX used the AWX encryption with no issue.
    # We still override it here so that we can prevent_search() on it.
    client_secret = prevent_search(
        oauth2_models.ClientSecretField(
            max_length=255,
            blank=True,
            default=generate_client_secret,
            db_index=True,
            help_text=_("Hashed on Save. Copy it now if this is a new secret."),
        )
    )

    client_type = models.CharField(
        max_length=32, choices=CLIENT_TYPES, help_text=_('Set to Public or Confidential depending on how secure the client device is.')
    )
    skip_authorization = models.BooleanField(default=False, help_text=_('Set True to skip authorization step for completely trusted applications.'))
    authorization_grant_type = models.CharField(
        max_length=32, choices=GRANT_TYPES, help_text=_('The Grant type the user must use for acquire tokens for this application.')
    )
    updated = None  # Tracked in CommonModel with 'modified', no need for this

    def get_absolute_url(self):
        # This is kind of annoying. This method lives on the superclass and we check for it in CommonModel.
        # But better would be to not have this method and let the CommonModel logic fall back to the "right" way of finding this.
        return get_relative_url(f'{self.router_basename}-detail', kwargs={'pk': self.pk})
