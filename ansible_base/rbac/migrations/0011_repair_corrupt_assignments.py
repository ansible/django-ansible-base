from django.db import migrations


def repair_corrupt_assignments(apps, schema_editor):
    from ansible_base.rbac.repair import repair_assignment_corruption

    repair_assignment_corruption(apps=apps, schema_editor=schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('dab_rbac', '0010_roleteamassignment_unique_global_team_assignment_and_more'),
    ]

    operations = [
        migrations.RunPython(repair_corrupt_assignments, migrations.RunPython.noop),
    ]
