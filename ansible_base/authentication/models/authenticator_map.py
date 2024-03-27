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

from django.db import models

from ansible_base.lib.abstract_models.common import NamedCommonModel

from .authenticator import Authenticator


class AuthenticatorMap(NamedCommonModel):
    router_basename = 'authenticatormap'

    class Meta:
        # If the map type is a team then we must have an org/team
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_require_org_team_if_team_map",
                check=(~models.Q(map_type='team') | models.Q(team__isnull=False) & models.Q(organization__isnull=False)),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_require_org_if_org_map",
                check=(~models.Q(map_type='organization') | models.Q(organization__isnull=False)),
            ),
        ]
        unique_together = ['name', 'authenticator']

    authenticator = models.ForeignKey(
        Authenticator,
        null=False,
        on_delete=models.CASCADE,
        help_text="The authenticator this mapping belongs to",
        related_name="authenticator_maps",
    )
    revoke = models.BooleanField(
        null=False,
        default=False,
        help_text="If a user does not meet this rule should we revoke the permission",
    )
    map_type = models.CharField(
        max_length=17,
        null=False,
        default="team",
        choices=[
            ('team', 'team'),
            ('is_superuser', 'is_superuser'),
            ('is_system_auditor', 'is_system_auditor'),
            ('allow', 'allow'),
            ('organization', 'organization'),
        ],
        help_text='What does the map work on, a team, a user flag or is this an allow rule',
    )
    team = models.CharField(
        max_length=512,
        null=True,
        default=None,
        blank=True,
        help_text='A team name this rule works on',
    )
    organization = models.CharField(
        max_length=512,
        null=True,
        default=None,
        blank=True,
        help_text='An organization name this rule works on',
    )
    triggers = models.JSONField(
        null=False,
        default=dict,
        blank=True,
        help_text="Trigger information for this rule",
    )
    order = models.PositiveIntegerField(
        null=False,
        default=0,
        help_text=(
            "The order in which this rule should be processed, smaller numbers are of higher precedence. "
            "Items with the same order will be executed in random order"
        ),
    )
