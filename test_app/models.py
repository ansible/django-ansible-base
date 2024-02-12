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
    encryptioner = models.ForeignKey('test_app.EncryptionModel', on_delete=models.SET_NULL, null=True)


class ResourceMigrationTestModel(models.Model):
    name = models.CharField(max_length=255)


class EncryptionModel(NamedCommonModel):
    router_basename = 'encryption_test_model'

    class Meta:
        app_label = "test_app"

    encrypted_fields = ['testing1', 'testing2']

    testing1 = models.CharField(max_length=1, null=True, default='a')
    testing2 = models.CharField(max_length=1, null=True, default='b')


class RelatedFieldsTestModel(CommonModel):
    users = models.ManyToManyField(User, related_name='related_fields_test_model_users')

    teams_with_no_view = models.ManyToManyField(Team, related_name='related_fields_test_model_teams_with_no_view')

    more_teams = models.ManyToManyField(Team, related_name='related_fields_test_model_more_teams')

    ignore_relations = ['teams_with_no_view']
