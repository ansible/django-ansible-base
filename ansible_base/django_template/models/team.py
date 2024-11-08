from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.activitystream.models import AuditableModel
from ansible_base.django_template.models.mixins import UsersMembersMixin
from ansible_base.lib.abstract_models import AbstractTeam
from ansible_base.rbac.managed import TeamAdmin, TeamMember
from ansible_base.resource_registry.fields import AnsibleResourceField


class AbstractTemplateTeam(UsersMembersMixin, AbstractTeam, AuditableModel):
    class Meta(AbstractTeam.Meta):
        abstract = True

    admin_rd_name = TeamAdmin.name
    member_rd_name = TeamMember.name

    resource = AnsibleResourceField(primary_key_field="id")

    ignore_relations = ['parents', 'teams']

    # If we remove this in the future, you can also remove the ignore_relations
    parents = models.ManyToManyField(
        settings.ANSIBLE_BASE_TEAM_MODEL,
        blank=True,
        symmetrical=False,
        help_text=_("The list of teams that are parents of this team"),
    )
