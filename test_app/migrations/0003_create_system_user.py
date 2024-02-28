from django.conf import settings
from django.db import migrations
from django.utils import timezone


def create_system_user(apps, schema_editor):
    """
    Create the system user using the username in settings.

    The user is self-referential in its created_by and modified_by fields.
    It is inactive, only used for attributing internal changes to the system.
    """
    User = apps.get_model(settings.AUTH_USER_MODEL)

    system_username = settings.SYSTEM_USERNAME
    if not User.objects.filter(username=system_username).exists():
        now = timezone.now()
        system_user = User.objects.create(username=system_username, is_active=False, created_on=now, modified_on=now)
        system_user.created_by = system_user
        system_user.modified_by = system_user
        system_user.save()


class Migration(migrations.Migration):

    dependencies = [
        ('test_app', '0002_set_up_resources_test_data'),
    ]

    operations = [
        migrations.RunPython(create_system_user),
    ]
