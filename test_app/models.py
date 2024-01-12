from django.db import models

from ansible_base.models.common import NamedCommonModel


class EncryptionModel(NamedCommonModel):
    class Meta:
        app_label = "test_app"

    encrypted_fields = ['testing1', 'testing2']

    testing1 = models.CharField(max_length=1, null=True, default='a')
    testing2 = models.CharField(max_length=1, null=True, default='b')
