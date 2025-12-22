###
# Noop migration due to removal of FEATURE_GATEWAY_IPV6_USAGE_ENABLED
###

# FileHash: a20d9c75cd62ebcf19ceb223985fe68f191f75b52d2e6c123b31944e4a5e28f6

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dab_feature_flags', '0001_initial'),
    ]

    operations = [
    ]
