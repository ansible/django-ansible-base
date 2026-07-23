from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dab_oauth2_provider', '0009_add_openid_roles_scopes'),
    ]

    # Two-step operation: AddField(default=False) backfills existing rows with False,
    # then AlterField(default=True) sets the default for new records only.
    operations = [
        migrations.AddField(
            model_name='oauth2application',
            name='pkce_required',
            field=models.BooleanField(default=False, help_text='When True, clients must use PKCE (send code_challenge) when requesting authorization codes for this application.'),
        ),
        migrations.AlterField(
            model_name='oauth2application',
            name='pkce_required',
            field=models.BooleanField(default=True, verbose_name='PKCE Required', help_text='When True, clients must use PKCE (send code_challenge) when requesting authorization codes for this application.'),
        ),
    ]
