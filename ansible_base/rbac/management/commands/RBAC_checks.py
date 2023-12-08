from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import ObjectRole, RoleDefinition


class Command(BaseCommand):
    help = "Runs bug checking sanity checks, gets scale metrics, and recommendations for Role Based Access Control"

    def check_role_definitions(self):
        rd_ct = RoleDefinition.objects.count()
        self.stdout.write(f'Inspecting {rd_ct} role definitions')
        self.stdout.write('  checking for minimum of view permission')
        indexed_rds = defaultdict(list)
        for rd in RoleDefinition.objects.prefetch_related('permissions'):
            perm_list = list(rd.permissions.values_list('codename', flat=True))
            if not any(p.startswith('view_') for p in perm_list):
                self.stdout.write(self.style.WARNING(f'Role definition {rd.name} does not list any view permissions and this is considered invalid'))
                self.has_issues = True
            perm_set = frozenset(perm_list)
            indexed_rds[perm_set].append(rd)

        self.stdout.write('  checking for duplicate role definitions')
        for perm_set, rd_list in indexed_rds.items():
            if len(rd_list) > 1:
                self.stdout.write(self.style.WARNING('Found duplicate role definitions with same permissions list:'))
                for rd in rd_list:
                    self.stdout.write(f'   {rd}')

        object_role_ct = ObjectRole.objects.count()
        self.stdout.write(f'Inspecting {object_role_ct} object roles')
        self.stdout.write('  checking for invalid permissions for model type')
        for role in ObjectRole.objects.prefetch_related('role_definition__permissions', 'content_type'):
            for permission in role.role_definition.permissions.all():
                if permission.content_type_id != role.content_type_id:
                    if permission.content_type.model_class() not in set(
                        cls for filter_path, cls in permission_registry.get_child_models(role.content_type.model_class())
                    ):
                        self.stdout.write(
                            self.style.WARNING(f'Object role {role} has permission {permission.codename} for an unlike content type {permission.content_type}')
                        )

    def check_object_roles(self):
        self.stdout.write('  checking for up-to-date role evaluations')
        for role in ObjectRole.objects.all():
            to_delete, to_add = role.needed_cache_updates()
            if to_delete or to_add:
                self.stdout.write(
                    self.style.WARNING(f'Object role {role} does not have up-to-date role evaluations cached, this can happen if someone bypasses signals')
                )

        self.stdout.write('  checking for missing content object')
        for role in ObjectRole.objects.all():
            if not role.content_object:
                self.stdout.write(self.style.WARNING(f'Object role {role} has been orphaned, indicating that post_delete signals are broken'))

    def handle(self, *args, **options):
        self.has_issues = False
        self.check_role_definitions()
        self.check_object_roles()
        if not self.has_issues:
            self.stdout.write(self.style.SUCCESS('No issues were found'))
        else:
            raise CommandError('Checks completed, some potential issues were noted')
