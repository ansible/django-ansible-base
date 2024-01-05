from django.core.management.base import BaseCommand

from ansible_base.models.rbac import ObjectRole, RoleDefinition
from ansible_base.rbac import permission_registry


class Command(BaseCommand):
    help = "Runs bug checking sanity checks, gets scale metrics, and reccomendations for Role Based Access Control"

    def handle(self, *args, **options):
        rd_ct = RoleDefinition.objects.count()
        self.stdout.write(f'Inspecting {rd_ct} role definitions')
        self.stdout.write('  checking for minimum of view permission')
        indexed_rds = {}
        for rd in RoleDefinition.objects.prefetch_related('permissions'):
            perm_list = list(rd.permissions.values_list('codename', flat=True))
            if 'view' not in ' '.join(perm_list):
                self.stdout.write(f'Role definition {rd.name} does not list any view permissions and this is considered invalid')
            perm_set = frozenset(perm_list)
            indexed_rds.setdefault(perm_set, [])
            indexed_rds[perm_set].append(rd)

        self.stdout.write('  checking for duplicate role definitions')
        for perm_set, rd_list in indexed_rds.items():
            if len(rd_list) > 1:
                self.stdout.write('Found duplicate role definitions with same permissions list:')
                for rd in rd_list:
                    self.stdout.write(f'   {rd}')

        self.stdout.write(f'Inspecting {ObjectRole.objects.count()} object roles')
        self.stdout.write('  checking for invalid permissions for model type')
        for role in ObjectRole.objects.prefetch_related('role_definition__permissions', 'content_type'):
            for permission in role.role_definition.permissions.all():
                if permission.content_type_id != role.content_type_id:
                    if permission.content_type.model_class() not in set(
                        cls for filter_path, cls in permission_registry.get_child_models(role.content_type.model)
                    ):
                        self.stdout.write(f'Object role {role} has permission {permission.codename} for an unlike content type {permission.content_type}')

        self.stdout.write('  checking for up-to-date role evaluations')
        for role in ObjectRole.objects.all():
            to_delete, to_add = role.needed_cache_updates()
            if to_delete or to_add:
                self.stdout.write(f'Object role {role} does not have up-to-date role evaluations cached, this can happen if someone bypasses signals')

        self.stdout.write('  checking for missing content object')
        for role in ObjectRole.objects.all():
            if not role.content_object:
                self.stdout.write(f'Object role {role} has been orphaned, indicating that post_delete signals are broken')
