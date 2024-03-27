"""Organization models."""

#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .common import NamedCommonModel


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
        help_text=_("The organization of this team."),
    )
