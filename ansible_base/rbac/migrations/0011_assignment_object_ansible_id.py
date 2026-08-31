import django.db.models.deletion
import uuid
from django.db import migrations, models


def repair_and_backfill(apps, schema_editor):
    from ansible_base.rbac.repair import repair_assignment_corruption

    repair_assignment_corruption(apps=apps, schema_editor=schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('dab_rbac', '0010_roleteamassignment_unique_global_team_assignment_and_more'),
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
        migrations.RunPython(repair_and_backfill, migrations.RunPython.noop),
    ]
