from django.db import migrations, models

from ansible_base.rbac.backfill import backfill_object_ansible_id


class Migration(migrations.Migration):
    dependencies = [
        ('dab_rbac', '0010_roleteamassignment_unique_global_team_assignment_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='roleuserassignment',
            name='object_ansible_id',
            field=models.UUIDField(blank=True, help_text='Cached ansible_id of the resource this assignment applies to.', null=True),
        ),
        migrations.AddField(
            model_name='roleteamassignment',
            name='object_ansible_id',
            field=models.UUIDField(blank=True, help_text='Cached ansible_id of the resource this assignment applies to.', null=True),
        ),
        migrations.RunPython(backfill_object_ansible_id, migrations.RunPython.noop),
    ]
