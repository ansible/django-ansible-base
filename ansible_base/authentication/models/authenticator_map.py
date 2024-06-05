from django.db import models
from django.utils.translation import gettext_lazy as _

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
        help_text=(_("The authenticator this mapping belongs to")),
        related_name="authenticator_maps",
    )
    revoke = models.BooleanField(
        null=False,
        default=False,
        help_text=(_("If a user does not meet this rule should we revoke the permission")),
    )

    map_type = models.CharField(
        max_length=17,
        null=False,
        default="team",
        choices=[
            ('allow', 'allow'),
            ('is_superuser', 'is_superuser'),
            ('role', 'role'),
            ('organization', 'organization'),
            ('team', 'team'),
        ],
        help_text=(_('What does the map work on, a team, organization, a user flag or is this an allow rule')),
    )

    role = models.CharField(
        max_length=512,
        null=True,
        default=None,
        blank=True,
        help_text=(_("The role this map will grant the authenticating user to the targeted object")),
    )

    team = models.CharField(
        max_length=512,
        null=True,
        default=None,
        blank=True,
        help_text=(_('A team name this rule works on')),
    )
    organization = models.CharField(
        max_length=512,
        null=True,
        default=None,
        blank=True,
        help_text=(_('An organization name this rule works on')),
    )
    triggers = models.JSONField(
        null=False,
        default=dict,
        blank=True,
        help_text=(_("Trigger information for this rule")),
    )
    order = models.PositiveIntegerField(
        null=False,
        default=0,
        help_text=(
            _(
                "The order in which this rule should be processed, smaller numbers are of higher precedence. "
                "Items with the same order will be executed in random order"
            )
        ),
    )
