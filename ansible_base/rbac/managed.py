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
        return _(self.name)  # type: ignore[return-value]

    def get_content_type(self, apps):
        model = self.get_model(apps)
        if model is None:
            return None
        # NOTE: this is subject to major migration-related hazards
        try:
            content_type_cls = apps.get_model('dab_rbac', 'DABContentType')
        except LookupError:
            content_type_cls = apps.get_model('contenttypes', 'ContentType')
        return content_type_cls.objects.get_for_model(model)

    def refresh_permissions(self, rd, apps):
        """Make role permissions equal what the managed definition specifies"""
        permission_cls = apps.get_model('dab_rbac', 'DABPermission')

        # Desired permission codenames from managed source
        desired_codenames = set(self.get_permissions(apps))

        # Resolve to actual permission objects or error
        desired_permissions = []
        for codename in desired_codenames:
            try:
                if '.' in codename:
                    perm = permission_cls.objects.get(api_slug=codename)
                else:
                    perm = permission_cls.objects.get(codename=codename)
                desired_permissions.append(perm)
            except permission_cls.DoesNotExist:
                db_codenames = list(permission_cls.objects.values_list('codename', flat=True))
                raise permission_cls.DoesNotExist(
                    f'Permission codename "{codename}" does not exist.\n'
                    f'Managed role: {self}\nExpected: {sorted(desired_codenames)}\n'
                    f'Available in DB: {sorted(db_codenames)}'
                )

        desired_set = set(desired_permissions)
        current_set = set(rd.permissions.all())

        to_add = desired_set - current_set
        to_remove = current_set - desired_set

        if not to_add and not to_remove:
            logger.info(f'No permission changes needed for role "{self.name}"')
        else:
            if to_add:
                rd.permissions.add(*to_add)
                added_codenames = sorted(p.codename for p in to_add)
                logger.info(f'Added permissions to role "{self.name}": {added_codenames}')

            if to_remove:
                rd.permissions.remove(*to_remove)
                removed_codenames = sorted(p.codename for p in to_remove)
                logger.info(f'Removed permissions from role "{self.name}": {removed_codenames}')

        logger.debug(f'Final permissions for role "{self.name}": {sorted(p.codename for p in rd.permissions.all())}')

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
            self.refresh_permissions(rd, apps=apps)
            logger.debug(f'Data of {self.name} role definition: {defaults}')
        return rd, created

    def allowed_permissions_by_model(self, model: Optional[Type[Model]]) -> dict[Type, list[str]]:
        from ansible_base.rbac.validators import permissions_allowed_for_role

        return permissions_allowed_for_role(model)

    def allowed_permissions_slug_list(self, model: Optional[Type[Model]]) -> set[str]:
        "Returns all possible permissions for model in terms format of awx.change_inventory"
        from ansible_base.rbac.remote import get_resource_prefix

        slug_list = set()
        for child_model, child_codenames in self.allowed_permissions_by_model(model).items():
            prefix = get_resource_prefix(child_model)
            for codename in child_codenames:
                slug_list.add(f'{prefix}.{codename}')
        return slug_list


class ManagedAdminBase(ManagedRoleConstructor):
    description = gettext_noop("Has all permissions to a single {model_name_verbose}")

    def get_permissions(self, apps) -> set[str]:
        """All permissions possible for the associated model"""
        return self.allowed_permissions_slug_list(self.get_model(apps))


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
        return {api_slug for api_slug in self.allowed_permissions_slug_list(self.get_model(apps)) if '.view' in api_slug}


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

    def get_permissions(self, apps) -> set[str]:
        perms = super().get_permissions(apps)
        team_model = apps.get_model(settings.ANSIBLE_BASE_TEAM_MODEL)
        perms.add(f'view_{team_model._meta.model_name}')
        return perms


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
