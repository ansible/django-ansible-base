from django.db import migrations

from ansible_base.oauth2_provider.migrations._utils import hash_tokens


class Migration(migrations.Migration):
    dependencies = [
        ("dab_oauth2_provider", "0004_alter_oauth2accesstoken_scope"),
    ]

    operations = [
        migrations.RunPython(hash_tokens),
    ]
