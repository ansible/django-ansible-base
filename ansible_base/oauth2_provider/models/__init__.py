from .access_token import OAuth2AccessToken
from .application import OAuth2Application
from .id_token import OAuth2IDToken
from .refresh_token import OAuth2RefreshToken

__all__ = (
    'OAuth2AccessToken',
    'OAuth2Application',
    'OAuth2IDToken',
    'OAuth2RefreshToken',
)

#
# There were a lot of problems making the initial migrations for this class
# See https://github.com/jazzband/django-oauth-toolkit/issues/634 which helped
#
# Here were my steps:
#  1. Make sure 'ansible_base.oauth2_provider' is in test_app INSTALLED_APPS (this already should be)
#  2. Comment out all OAUTH2_ settings in ansible_base/lib/dynamic_config/dynamic_settings.py which reference dab_oauth2_provider.*
#  3. Change all model classes to:
#         remove oauth2_models.Abstract* as superclasses (including the meta ones)
#         comment out the "import oauth2_provider.models as oauth2_models" imports
#  4. ./manage.py makemigrations dab_oauth2_provider
#  5. Edit the created 0001 migration and delete the dpendency on ('test_app', '000X')
#  6. ./manage.py migrate dab_oauth2_provider
#  7. Look at the generated migration, if this has a direct reference to your applications organization model in OAuth2Application model we need to update it
#     for example, if it looks like:
#       ('organization', ... to='<your app>.organization')),
#     We want to change this to reference the setting:
#       ('organization', ... to=settings.ANSIBLE_BASE_ORGANIZATION_MODEL)),
#     We should also add this in the migration dependencies:
#       migrations.swappable_dependency(settings.ANSIBLE_BASE_ORGANIZATION_MODEL),
#  8. Uncomment all OAUTH2_PROVIDER_* settings
#  9. Revert step 3
#  10. gateway-manage makemigrations && gateway-manage migrate ansible_base
#       When you do this django does not realize that you are creating an initial migration and tell you its impossible to migrate so fields
#       It will ask you to either: 1. Enter a default 2. Quit
#       Tell it to use the default if it has one populated at the prompt. Other wise use django.utils.timezone.now for timestamps and  '' for other items
#       This wont matter for us because there will be no data in the tables between these two migrations
#  11. You can now combine the migration into one.
#      Add the `import uuid` to the top of the initial migration file
#      Copy all of the operations from the second file to the first
#      Find the AddFields commands for oauth2refreshtoken.access_token and oauth2accesstoken.source_refresh_token and move them to the end of the operations
#      If desired, convert the remaining AddFilds into actual fields on the table creation. For example:
#           migrations.AddField(
#                model_name='oauth2accesstoken',
#                name='created',
#                field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
#                preserve_default=False,
#            ),
#      Would become the following field on the oauth2accesstoken table:
#            ('created', models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now)),
#      Next put the table creation in the following order: OAuth2Application, OAuth2IDToken, OAuth2RefreshToken, OAuth2AccessToken
#      Finally, be sure to add this to the migration file:
#            run_before = [
#              ('oauth2_provider', '0001_initial'),
#            ]
#  12. Delete the new migration
#  13. zero out the initial migration with: ./manage.py migrate dab_oauth2_provider zero
#  14. Make the actual migration with: ./manage.py migrate dab_oauth2_provider
