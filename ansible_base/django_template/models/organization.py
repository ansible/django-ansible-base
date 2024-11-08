from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.activitystream.models import AuditableModel
from ansible_base.django_template.models.mixins import UsersMembersMixin
from ansible_base.lib.abstract_models.organization import AbstractOrganization
from ansible_base.lib.utils.auth import get_team_model
from ansible_base.rbac.managed import OrganizationAdmin, OrganizationMember
from ansible_base.rbac.models import ObjectRole
from ansible_base.resource_registry.fields import AnsibleResourceField


class AbstractTemplateOrganization(UsersMembersMixin, AbstractOrganization, AuditableModel):
    class Meta:
        abstract = True

    admin_rd_name = OrganizationAdmin.name
    member_rd_name = OrganizationMember.name

    resource = AnsibleResourceField(primary_key_field="id")

    managed = models.BooleanField(
        editable=False,
        blank=False,
        default=False,
        help_text=_("Indicates if this organization is managed by the system. It cannot be modified once created."),
    )

    def get_summary_fields(self):
        # TODO: We should probably come up with a more codified and standard
        # way to return this kind of info from models.
        response = super().get_summary_fields()
        response["related_field_counts"] = {}
        if get_team_model(return_none_on_error=True) is not None:
            response["related_field_counts"]["teams"] = self.teams.count()

        response["related_field_counts"]["users"] = get_user_model().objects.filter(
            has_roles__in=ObjectRole.objects.filter(object_id=self.pk, role_definition__name=self.member_rd_name)
        ).count()

        return response
