from django.core.management.base import BaseCommand
from django.db.models import Q

from ansible_base.rbac.models import ObjectRole
from ansible_base.rbac.permission_registry import permission_registry

EMPTY_PARENT_REF = Q(parent_reference='') | Q(parent_reference__isnull=True)


class Command(BaseCommand):
    help = "Backfill ObjectRole.parent_reference for local models that have a registered parent FK."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes.')

    def _build_parent_map(self, cls, parent_field_name, ct):
        """Build a mapping of object_id -> parent_id for ObjectRoles with empty parent_reference."""
        empty_roles = ObjectRole.objects.filter(content_type=ct).filter(EMPTY_PARENT_REF)
        if not empty_roles.exists():
            return {}

        parent_fk_col = f'{parent_field_name}_id'
        object_ids = list(empty_roles.values_list('object_id', flat=True))

        pk_field = cls._meta.pk
        if pk_field.get_internal_type() in ('AutoField', 'IntegerField', 'BigAutoField'):
            object_ids = [int(oid) for oid in object_ids if oid.isdigit()]

        objects = cls.objects.filter(pk__in=object_ids).values_list('pk', parent_fk_col)
        return {str(pk): str(parent_id) for pk, parent_id in objects if parent_id is not None}

    def _apply_updates(self, cls, ct, parent_map, dry_run):
        """Apply parent_reference updates for a single model class. Returns count of updated roles."""
        count = 0
        for object_id, parent_id in parent_map.items():
            if dry_run:
                self.stdout.write(f'  Would update {cls.__name__} object_id={object_id} -> parent_reference={parent_id}')
                count += 1
            else:
                count += ObjectRole.objects.filter(content_type=ct, object_id=object_id).filter(EMPTY_PARENT_REF).update(parent_reference=parent_id)

        if count:
            action = 'Would update' if dry_run else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{action} {count} ObjectRole(s) for {cls.__name__}'))
        return count

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        total_updated = 0

        from ansible_base.rbac.models.content_type import DABContentType

        for cls in permission_registry.all_registered_models:
            parent_field_name = permission_registry.get_parent_fd_name(cls)
            if not parent_field_name:
                continue

            ct = DABContentType.objects.get_for_model(cls)
            parent_map = self._build_parent_map(cls, parent_field_name, ct)
            if not parent_map:
                continue

            total_updated += self._apply_updates(cls, ct, parent_map, dry_run)

        if total_updated:
            action = 'would be updated' if dry_run else 'updated'
            self.stdout.write(self.style.SUCCESS(f'\nTotal: {total_updated} ObjectRole(s) {action}.'))
        else:
            self.stdout.write('No ObjectRoles need parent_reference backfill.')
