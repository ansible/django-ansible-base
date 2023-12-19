"""Organization models."""
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
