from django.db import migrations

from ansible_base.rbac.repair import repair_assignment_corruption


def repair_corrupt_assignments(apps, schema_editor):
    repair_assignment_corruption(apps=apps, schema_editor=schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('dab_rbac', '0010_roleteamassignment_unique_global_team_assignment_and_more'),
    ]

    operations = [
        migrations.RunPython(repair_corrupt_assignments, migrations.RunPython.noop),
    ]
