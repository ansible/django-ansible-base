###
# Noop migration due to removal of FEATURE_DISPATCHERD_ENABLED
###

# FileHash: a85e30c0d37e6aeac8dc04b9dd37e7dc0d06a9793e85af00f01bef100165df6f

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dab_feature_flags', '0003_manual_20260113'),
    ]

    operations = [
    ]
