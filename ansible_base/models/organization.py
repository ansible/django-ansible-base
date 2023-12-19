"""Organization models."""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .common import UniqueNamedCommonModel


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

    teams = models.ManyToManyField(
        settings.ANSIBLE_BASE_TEAM_MODEL,
        related_name="organizations",
        help_text=_("The list of teams in this organization."),
    )
