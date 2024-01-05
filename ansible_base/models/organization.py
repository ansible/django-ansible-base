"""Organization models."""
from django.conf import settings
from django.db import models

from .common import UniqueNamedCommonModel


class AbstractOrganization(UniqueNamedCommonModel):
    """An abstract base class for organizations."""

    class Meta:
        abstract = True

    description = models.TextField(
        null=False,
        default="",
        help_text="The organization description.",
    )

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="organizations",
        help_text="The list of users in this organization.",
    )

    teams = models.ManyToManyField(
        settings.ROLE_TEAM_MODEL,
        related_name="organizations",
        help_text="The list of teams in this organization.",
    )
