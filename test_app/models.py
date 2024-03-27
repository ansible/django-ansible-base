#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models import AbstractOrganization, AbstractTeam, CommonModel, ImmutableCommonModel, ImmutableModel, NamedCommonModel
from ansible_base.lib.utils.models import user_summary_fields
from ansible_base.rbac import permission_registry
from ansible_base.resource_registry.fields import AnsibleResourceField


class Organization(AbstractOrganization):
    resource = AnsibleResourceField(primary_key_field="id")


class User(AbstractUser, CommonModel, AuditableModel):
    resource = AnsibleResourceField(primary_key_field="id")

    def summary_fields(self):
        return user_summary_fields(self)


class Team(AbstractTeam):
    resource = AnsibleResourceField(primary_key_field="id")
    tracked_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='tracked_teams', blank=True)
    team_parents = models.ManyToManyField('Team', related_name='team_children', blank=True)

    encryptioner = models.ForeignKey('test_app.EncryptionModel', on_delete=models.SET_NULL, null=True)

    class Meta:
        app_label = 'test_app'
        abstract = False
        unique_together = [('organization', 'name')]
        ordering = ('organization__name', 'name')
        permissions = [('member_team', 'Has all roles assigned to this team')]


class ResourceMigrationTestModel(models.Model):
    name = models.CharField(max_length=255)


class EncryptionModel(NamedCommonModel):
    router_basename = 'encryption_test_model'

    class Meta:
        app_label = "test_app"

    encrypted_fields = ['testing1', 'testing2']

    testing1 = models.CharField(max_length=400, null=True, default='a')
    testing2 = models.CharField(max_length=400, null=True, default='b')


class RelatedFieldsTestModel(CommonModel):
    users = models.ManyToManyField(User, related_name='related_fields_test_model_users')

    teams_with_no_view = models.ManyToManyField(Team, related_name='related_fields_test_model_teams_with_no_view')

    more_teams = models.ManyToManyField(Team, related_name='related_fields_test_model_more_teams')

    ignore_relations = ['teams_with_no_view']


class ImmutableLogEntry(ImmutableCommonModel):
    """
    Testing ImmutableCommonModel
    """

    message = models.CharField(max_length=400)


class ImmutableLogEntryNotCommon(ImmutableModel):
    """
    Testing the more generic ImmutableModel
    """

    message = models.CharField(max_length=400)


class Inventory(models.Model):
    "Simple example of a child object, it has a link to its parent organization"
    name = models.CharField(max_length=512)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True)

    class Meta:
        app_label = 'test_app'
        permissions = [('update_inventory', 'Do inventory updates')]

    def summary_fields(self):
        return {"id": self.id, "name": self.name}


class InstanceGroup(models.Model):
    "Example of an object with no parent object, a root resource, a lone wolf"
    name = models.CharField(max_length=512)


class Namespace(models.Model):
    "Example of a child object with its own child objects"
    name = models.CharField(max_length=64, unique=True, blank=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)


class CollectionImport(models.Model):
    "Example of a child of a child object, organization is implied by its namespace"
    name = models.CharField(max_length=64, unique=True, blank=False)
    namespace = models.ForeignKey(Namespace, on_delete=models.CASCADE)


class ExampleEvent(models.Model):
    "Example of a model which is not registered in permission registry in the first place"
    name = models.CharField(max_length=64, unique=True, blank=False)


class Cow(models.Model):
    "This model has a special action it can do, which is to give advice"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)

    class Meta:
        app_label = 'test_app'
        permissions = [('say_cow', 'Make cow say some advice')]


class UUIDModel(models.Model):
    "Tests that system works with a model that has a string uuid primary key"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)


class ImmutableTask(models.Model):
    "Hypothetical immutable task-like thing, can be created and canceled but not edited"

    class Meta:
        default_permissions = ('add', 'view', 'delete')
        permissions = [('cancel_immutabletask', 'Stop this task from running')]


class ParentName(models.Model):
    "Tests that system works with a parent field name different from parent model name"
    my_organization = models.ForeignKey(Organization, on_delete=models.CASCADE)


class PositionModel(models.Model):
    "Uses a primary key other than id to test that everything still works"
    position = models.BigIntegerField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)


class WeirdPerm(models.Model):
    "Uses a weird permission name"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)

    class Meta:
        app_label = 'test_app'
        permissions = [("I'm a lovely coconut", "You can be a lovely coconut with this object"), ("crack", "Can crack open this coconut")]


class ProxyInventory(Inventory):
    "This is not a registered permissions model. It exposes issues with duplicate permission codenames."

    class Meta:
        proxy = True
        permissions = [
            ("view_inventory", "Can view inventory"),
            ("change_inventory", "Can change inventory"),
            ("add_inventory", "Can add inventory"),
            ("delete_inventory", "Can delete inventory"),
        ]


class Original1(NamedCommonModel):
    "Registered with the Resource Registry"
    pass


class Proxy1(Original1):
    "Not registered"

    class Meta:
        proxy = True


class Original2(NamedCommonModel):
    "Not registered"
    pass


class Proxy2(Original2):
    "Registered with the Resource Registry"

    class Meta:
        proxy = True


permission_registry.register(Organization, Inventory, Namespace, Team, Cow, UUIDModel, PositionModel, WeirdPerm)
permission_registry.register(ParentName, parent_field_name='my_organization')
permission_registry.register(CollectionImport, parent_field_name='namespace')
permission_registry.register(InstanceGroup, ImmutableTask, parent_field_name=None)

permission_registry.track_relationship(Team, 'tracked_users', 'team-member')
permission_registry.track_relationship(Team, 'team_parents', 'team-member')


class MultipleFieldsModel(NamedCommonModel):
    class Meta:
        app_label = "test_app"

    char_field1 = models.CharField(max_length=100, null=True, default='a')
    char_field2 = models.CharField(max_length=100, null=True, default='b')
    int_field = models.PositiveIntegerField(null=True, default=1)
    bool_field = models.BooleanField(default=True)


class Animal(NamedCommonModel, AuditableModel):
    class Meta:
        app_label = "test_app"

    activity_stream_excluded_field_names = ['age']

    ANIMAL_KINDS = (
        ('dog', 'Dog'),
        ('cat', 'Cat'),
        ('fish', 'Fish'),
    )

    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    kind = models.CharField(max_length=4, choices=ANIMAL_KINDS, default='dog')
    age = models.PositiveIntegerField(null=True, default=1)
    people_friends = models.ManyToManyField(User, related_name='animal_friends', blank=True)


class City(NamedCommonModel, AuditableModel):
    class Meta:
        app_label = "test_app"

    activity_stream_limit_field_names = ['country']

    country = models.CharField(max_length=100, null=True, default='USA')
    population = models.PositiveIntegerField(null=True, default=1000)
