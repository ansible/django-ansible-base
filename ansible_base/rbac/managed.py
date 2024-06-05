import logging

from django.utils.translation import gettext_lazy as _, gettext_noop


logger = logging.getLogger('ansible_base.rbac.managed')


class ManagedRoleDefinition:
    def __init__(self, apps, overrides=None):
        if overrides:
            for key, value in overrides.items():
                setattr(self, key, value)

    def get_model(self):
        raise NotImplementedError

    def get_permissions(self) -> set[str]:
        raise NotImplementedError

    def get_translated_name(self) -> str:
        return _(self.name)

    def get_content_type(self, apps):
        content_type_cls = apps.get_model('contenttypes', 'ContentType')
        return content_type_cls.objects.get_for_model(self.get_model())

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
            permissions = self.get_permissions()
            permission_cls = apps.get_model('dab_rbac', 'DABPermission')
            perm_list = [permission_cls.objects.get(codename=str_perm) for str_perm in permissions]
            rd.permissions.add(*perm_list)
            logger.info(f'Created {self.shortname} managed role definition, name={self.name}')
            logger.debug(f'Data of {self.name} role definition: {defaults}')
            logger.debug(f'Permissions of {self.name} role definition: {permissions}')
        return rd, created


class AdminMixin:
    def get_permissions(self) -> set[str]:
        """All permissions possible for the associated model"""
        from ansible_base.rbac.validators import combine_values, permissions_allowed_for_role

        return combine_values(permissions_allowed_for_role(self.get_model()))


class OrganizationMixin:
    def get_model(self):
        from ansible_base.lib.utils.auth import get_organization_model

        return get_organization_model()


class TeamMixin:
    def get_model(self):
        from ansible_base.lib.utils.auth import get_team_model

        return get_team_model()


# Start shared role definitions


class SystemAuditor(ManagedRoleDefinition):
    name = gettext_noop("System Auditor")
    description = gettext_noop("Has view permissions to all objects")
    shortname = 'system_auditor'

    def get_model(self):
        return None

    def get_permissions(self):
        from ansible_base.rbac.permission_registry import permission_registry

        perm_list = []
        for cls in permission_registry.all_registered_models:
            if 'view' in cls._meta.default_permissions:
                perm_list.append(f'view_{cls._meta.model_name}')
            else:
                logger.warning(f'Model {cls._meta.model_name} lacks view permission for auditor role')
        return perm_list


class OrganizationAdmin(AdminMixin, OrganizationMixin, ManagedRoleDefinition):
    name = gettext_noop("Organization Admin")
    description = gettext_noop("Has all permissions to a single organization and all objects inside of it")
    shortname = 'org_admin'


class OrganizationMember(OrganizationMixin, ManagedRoleDefinition):
    name = gettext_noop("Organization Member")
    description = gettext_noop("Has all permissions given to a single team")
    shortname = 'org_member'

    def get_permissions(self) -> list[str]:
        """All permissions possible for the associated model"""
        org_model_name = self.get_model()._meta.model_name  # should be "organization"
        return [f'view_{org_model_name}', f'member_{org_model_name}']


class TeamAdmin(AdminMixin, TeamMixin, ManagedRoleDefinition):
    name = gettext_noop("Team Admin")
    description = gettext_noop("Can manage a single team and has all permissions given the team")
    shortname = 'team_admin'


class TeamMember(TeamMixin, ManagedRoleDefinition):
    name = gettext_noop("Team Member")
    description = gettext_noop("Has all permissions given to a single team")
    shortname = 'team_member'

    def get_permissions(self) -> list[str]:
        """All permissions possible for the associated model"""
        team_model_name = self.get_model()._meta.model_name  # should be "team"
        return [f'view_{team_model_name}', f'member_{team_model_name}']


# Setup for registry, ultimately exists inside of permission_registry


courtesy_registry = {}
for cls in (SystemAuditor, OrganizationAdmin, OrganizationMember, TeamAdmin, TeamMember):
    courtesy_registry[cls.shortname] = cls


def get_managed_role_entries(apps, setting_value: dict[str, dict]) -> dict[str, ManagedRoleDefinition]:
    """Constructs managed role definition (instructions for creating a managed role definition)

    from the entries in setting_value, expected to be from settings.ANSIBLE_BASE_MANAGED_ROLE_REGISTRY"""
    ret = {}
    for final_shortname, role_data in setting_value.items():
        lookup_shortname = role_data.get('shortname', final_shortname)
        cls = courtesy_registry[lookup_shortname]
        ret[final_shortname] = cls(apps=apps, overrides=role_data)
    return ret
