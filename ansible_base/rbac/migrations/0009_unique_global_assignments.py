"""
Data migration: remove duplicate global role assignments.

For each (actor, role_definition) pair where object_role IS NULL,
keeps the oldest row (lowest pk) and deletes the rest.
Safe to re-run — a second run is a no-op if no duplicates exist.

Migration 0010 adds the UniqueConstraint that prevents future duplicates.
"""

import logging

from django.db import migrations, models, transaction

logger = logging.getLogger('ansible_base.rbac.migrations')

BATCH_SIZE = 1000


def deduplicate_global_assignments(apps, schema_editor):
    """Remove duplicate global role assignments, keeping the oldest (lowest pk) for each."""
    for model_name, actor_field in [('RoleUserAssignment', 'user'), ('RoleTeamAssignment', 'team')]:
        cls = apps.get_model('dab_rbac', model_name)
        duplicates = (
            cls.objects.filter(object_role__isnull=True)
            .values(actor_field, 'role_definition')
            .annotate(min_pk=models.Min('pk'), cnt=models.Count('pk'))
            .filter(cnt__gt=1)
            .iterator()
        )
        total_deleted = 0
        for dup in duplicates:
            qs = cls.objects.filter(
                object_role__isnull=True,
                role_definition=dup['role_definition'],
                **{actor_field: dup[actor_field]},
            ).exclude(pk=dup['min_pk'])
            while True:
                batch_pks = list(qs.values_list('pk', flat=True)[:BATCH_SIZE])
                if not batch_pks:
                    break
                with transaction.atomic():
                    deleted_count, _ = cls.objects.filter(pk__in=batch_pks).delete()
                total_deleted += deleted_count
        if total_deleted:
            logger.info('Deleted %d duplicate global %s entries', total_deleted, model_name)


class Migration(migrations.Migration):

    dependencies = [
        ('dab_rbac', '0008_remote_permissions_cleanup'),
    ]

    operations = [
        migrations.RunPython(deduplicate_global_assignments, migrations.RunPython.noop),
    ]
