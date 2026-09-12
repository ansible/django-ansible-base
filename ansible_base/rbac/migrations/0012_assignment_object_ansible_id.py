from django.db import migrations, models

from ansible_base.rbac.backfill import backfill_object_ansible_id as _backfill


def backfill_object_ansible_id(apps, schema_editor):
    _backfill(apps=apps, schema_editor=schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('dab_rbac', '0011_repair_corrupt_assignments'),
    ]

    operations = [
        migrations.AddField(
            model_name='roleuserassignment',
            name='object_ansible_id',
            field=models.UUIDField(blank=True, null=True, help_text='Cached ansible_id of the resource this assignment applies to.'),
        ),
        migrations.AddField(
            model_name='roleteamassignment',
            name='object_ansible_id',
            field=models.UUIDField(blank=True, null=True, help_text='Cached ansible_id of the resource this assignment applies to.'),
        ),
        migrations.RunPython(backfill_object_ansible_id, migrations.RunPython.noop),
    ]
