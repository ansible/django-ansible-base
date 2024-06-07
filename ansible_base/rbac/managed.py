import logging
from typing import Optional, Type

from django.conf import settings
from django.db.models import Model
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

logger = logging.getLogger('ansible_base.rbac.managed')


class ManagedRoleConstructor:
    """Subclasses must define attributes, or override methods that use attribues
    - name
    - description
    - model_name
    - permission_list
    """

    def __init__(self, overrides=None):
        if overrides:
            for key, value in overrides.items():
                setattr(self, key, value)

    def get_model(self, apps):
        "It is intended that this will error if subclass did not set model_name"
        if self.model_name is None:
            return None
        return apps.get_model(self.model_name)

    def get_permissions(self, apps) -> set[str]:
        "It is intended that this will error if subclass did not set permission_list"
        return self.permission_list

    def get_translated_name(self) -> str:
        return _(self.name)

    def get_content_type(self, apps):
        model = self.get_model(apps)
        if model is None:
            return None
        content_type_cls = apps.get_model('contenttypes', 'ContentType')
        return content_type_cls.objects.get_for_model(model)

    def get_or_create(self, apps):
        "Create from a list of text-type permissions and do validation"
        role_definition_cls = apps.get_model('dab_rbac', 'RoleDefinition')
        defaults = {
            'description': self.description,
            'content_type': self.get_content_type(apps),
            'managed': True,
        }
        rd, created = role_definition_cls.objects.get_or_create(name=self.name, defaults=defaults)

        if created:
            permissions = self.get_permissions(apps)
            permission_cls = apps.get_model('dab_rbac', 'DABPermission')
            perm_list = [permission_cls.objects.get(codename=str_perm) for str_perm in permissions]
            rd.permissions.add(*perm_list)
            logger.info(f'Created {self.shortname} managed role definition, name={self.name}')
            logger.debug(f'Data of {self.name} role definition: {defaults}')
            logger.debug(f'Permissions of {self.name} role definition: {permissions}')
        return rd, created

    def allowed_permissions(self, model: Optional[Type[Model]]) -> set[str]:
        from ansible_base.rbac.validators import combine_values, permissions_allowed_for_role

        return combine_values(permissions_allowed_for_role(model))


class ManagedAdminBase(ManagedRoleConstructor):
    description = gettext_noop("Has all permissions to a single {model_name_verbose}")

    def get_permissions(self, apps) -> set[str]:
        """All permissions possible for the associated model"""
        return self.allowed_permissions(self.get_model(apps))


class ManagedActionBase(ManagedRoleConstructor):
    description = gettext_noop("Can take specified action for a single {model_name_verbose}")
    action = None

    def get_permissions(self, apps) -> set[str]:
        """Gives permission for one special action and includes view permission as well"""
        model_name = self.get_model(apps)._meta.model_name
        return {f'view_{model_name}', self.action}


class ManagedReadOnlyBase(ManagedRoleConstructor):
    """Given a certain type this managed role includes all possible view permissions for that type

    The type is defined in the subclass, so this is an abstract class
    """

    description = gettext_noop("Has all viewing related permissions that can be delegated via {model_name_verbose}")

    def get_permissions(self, apps) -> set[str]:
        return {codename for codename in self.allowed_permissions(self.get_model(apps)) if codename.startswith('view')}


class OrganizationMixin:
    model_name = settings.ANSIBLE_BASE_ORGANIZATION_MODEL


class TeamMixin:
    model_name = settings.ANSIBLE_BASE_TEAM_MODEL


# Start concrete shared role definitions


class SystemAuditor(ManagedReadOnlyBase):
    name = gettext_noop("System Auditor")
    description = gettext_noop("Has view permissions to all objects")
    model_name = None


class OrganizationAdmin(OrganizationMixin, ManagedAdminBase):
    name = gettext_noop("Organization Admin")
    description = gettext_noop("Has all permissions to a single organization and all objects inside of it")


class OrganizationMember(OrganizationMixin, ManagedActionBase):
    name = gettext_noop("Organization Member")
    description = gettext_noop("Has member permission to a single organization")
    action = 'member_organization'


class TeamAdmin(TeamMixin, ManagedAdminBase):
    name = gettext_noop("Team Admin")
    description = gettext_noop("Can manage a single team and inherits all role assignments to the team")


class TeamMember(TeamMixin, ManagedActionBase):
    name = gettext_noop("Team Member")
    description = gettext_noop("Inherits all role assignments to a single team")
    action = 'member_team'


# Setup for registry, ultimately exists inside of permission_registry


managed_role_templates = {
    'sys_auditor': SystemAuditor,
    'org_admin': OrganizationAdmin,
    'org_member': OrganizationMember,
    'team_admin': TeamAdmin,
    'team_member': TeamMember,
    # These are not fully functional on their own, but can be easily subclassed
    'admin_base': ManagedAdminBase,
    'action_base': ManagedActionBase,
}


def get_managed_role_constructors(apps, setting_value: dict[str, dict]) -> dict[str, ManagedRoleConstructor]:
    """Constructs managed role definition (instructions for creating a managed role definition)

    from the entries in setting_value, expected to be from settings.ANSIBLE_BASE_MANAGED_ROLE_REGISTRY"""
    ret = {}
    for shortname, role_data in setting_value.items():
        lookup_shortname = role_data.get('shortname', shortname)
        cls = managed_role_templates[lookup_shortname]
        overrides = role_data.copy()
        overrides['template_shortname'] = lookup_shortname
        overrides['shortname'] = shortname
        ret[shortname] = cls(overrides=overrides)
    return ret
