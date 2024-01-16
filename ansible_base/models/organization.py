"""Organization models."""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .common import NamedCommonModel, UniqueNamedCommonModel


class AbstractOrganization(UniqueNamedCommonModel):
    """An abstract base class for organizations."""

    class Meta:
        abstract = True

    description = models.TextField(
        null=False,
        default="",
        help_text=_("The organization description."),
    )

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="organizations",
        help_text=_("The list of users in this organization."),
    )


class AbstractTeam(NamedCommonModel):
    """
    An abstract base class for teams.
    A team groups users that work on the same resources, so that permissions can be assigned efficiently.
    """

    class Meta:
        abstract = True
        unique_together = [('organization', 'name')]
        ordering = ('organization__name', 'name')

    description = models.TextField(
        null=False,
        blank=True,
        default="",
        help_text=_("The team description."),
    )

    organization = models.ForeignKey(
        settings.ANSIBLE_BASE_ORGANIZATION_MODEL,
        blank=False,
        null=False,
        on_delete=models.CASCADE,
        related_name="teams",
        help_text=_("The organization of this team.")
    )
