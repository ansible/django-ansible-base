from django.contrib.auth.models import AbstractUser
from django.db import models

from ansible_base.lib.abstract_models import AbstractOrganization, AbstractTeam
from ansible_base.lib.abstract_models.common import CommonModel, NamedCommonModel
from ansible_base.lib.utils.models import user_summary_fields


class Organization(AbstractOrganization):
    pass


class User(AbstractUser, CommonModel):
    def summary_fields(self):
        return user_summary_fields(self)


class Team(AbstractTeam):
    encryptioner = models.ForeignKey('EncryptionModel', on_delete=models.SET_NULL, null=True)


class ResourceMigrationTestModel(models.Model):
    name = models.CharField(max_length=255)


class EncryptionModel(NamedCommonModel):
    router_basename = 'encryption_test_model'

    class Meta:
        app_label = "test_app"

    encrypted_fields = ['testing1', 'testing2']

    testing1 = models.CharField(max_length=1, null=True, default='a')
    testing2 = models.CharField(max_length=1, null=True, default='b')
