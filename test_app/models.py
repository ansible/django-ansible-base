import uuid

from django.conf import settings
from django.db import models
from django.db.models import JSONField
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models import (
    AbstractDABUser,
    AbstractOrganization,
    AbstractTeam,
    CommonModel,
    ImmutableCommonModel,
    ImmutableModel,
    NamedCommonModel,
)
from ansible_base.lib.utils.models import prevent_search, user_summary_fields
from ansible_base.rbac import permission_registry
from ansible_base.resource_registry.fields import AnsibleResourceField
from test_app.managers import UserUnmanagedManager


class Organization(AbstractOrganization):
    class Meta:
        ordering = ['id']
        permissions = [('member_organization', 'User is member of this organization')]

    resource = AnsibleResourceField(primary_key_field="id")

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='member_of_organizations',
        blank=True,
        help_text="The list of users on this organization",
    )

    admins = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='admin_of_organizations',
        blank=True,
        help_text="The list of admins for this organization",
    )

    extra_field = models.CharField(max_length=100, null=True)


class User(AbstractDABUser, CommonModel, AuditableModel):
    class Meta(AbstractDABUser.Meta):
        ordering = ['id']

    resource = AnsibleResourceField(primary_key_field="id")
    activity_stream_excluded_field_names = ['last_login']

    def summary_fields(self):
        return user_summary_fields(self)

    def get_authenticator_ids(self) -> list[int]:
        return list(self.authenticator_users.values_list('provider__id', flat=True))

    def get_authenticator_uids(self) -> list[str]:
        return list(self.authenticator_users.values_list('uid', flat=True).distinct())


class ManagedUser(User):
    managed = models.BooleanField(default=False)

    # By default, skip managed users (use .all_objects for all users queryset)
    objects = UserUnmanagedManager()


class Team(AbstractTeam):
    resource = AnsibleResourceField(primary_key_field="id")
    team_parents = models.ManyToManyField('Team', related_name='team_children', blank=True)

    encryptioner = models.ForeignKey('test_app.EncryptionModel', on_delete=models.SET_NULL, null=True)

    ignore_relations = []

    class Meta:
        app_label = 'test_app'
        ordering = ['id']
        abstract = False
        unique_together = [('organization', 'name')]
        # TODO(cutwater): Remove ordering by default on a model level and fix corresponding tests failures.
        #   This doesn't match the behavior of the AAP gateway and produces SQL queries that are not identical to AAP gateway.
        ordering = ('organization__name', 'name')
        permissions = [('member_team', 'Has all roles assigned to this team')]

    users = models.ManyToManyField(
        User,
        related_name='teams',
        blank=True,
        help_text="The list of users on this team",
    )

    admins = models.ManyToManyField(
        User,
        related_name='teams_administered',
        blank=True,
        help_text="The list of admins for this team",
    )


class ResourceMigrationTestModel(models.Model):
    name = models.CharField(max_length=255)


class EncryptionJSONModel(CommonModel):
    router_basename = 'encryption_json_test_model'

    class Meta:
        app_label = "test_app"
        ordering = ['id']

    encrypted_fields = ['testing1']

    testing1 = JSONField(null=True, default=dict)


class EncryptionModel(NamedCommonModel):
    router_basename = 'encryption_test_model'

    class Meta:
        app_label = "test_app"
        ordering = ['id']

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


class LogEntry(models.Model):
    """
    Testing a very specific conflict, where name conflicts with admin.LogEntry
    We have to use this model to test that RBAC and other registries do not get confused
    This model will be registered in permission registry, but not the admin.LogEntry
    """

    message = models.CharField(max_length=400)


class Inventory(models.Model):
    "Simple example of a child object, it has a link to its parent organization"
    name = models.CharField(max_length=512)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, related_name='inventories')
    credential = models.ForeignKey('test_app.Credential', on_delete=models.SET_NULL, null=True, related_name='inventories')

    class Meta:
        app_label = 'test_app'
        ordering = ['id']
        permissions = [('update_inventory', 'Do inventory updates')]

    def summary_fields(self):
        return {"id": self.id, "name": self.name}

    def validate_role_assignment(self, actor, role_definition, **kwargs):
        if isinstance(actor, User):
            name = actor.username
        if isinstance(actor, Team):
            name = actor.name
        if name == 'test-400':
            raise DRFValidationError({'detail': 'Role assignment not allowed 400'})
        if name == 'test-403':
            raise DRFPermissionDenied('Role assignment not allowed 403')


class Credential(models.Model):
    "Example of a model that gets used by other models"
    name = models.CharField(max_length=512)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, related_name='credentials')

    class Meta:
        app_label = 'test_app'
        ordering = ['id']
        permissions = [('use_credential', 'Apply credential to other models')]

    def summary_fields(self):
        return {"id": self.id, "name": self.name}


class InstanceGroup(models.Model):
    "Example of an object with no parent object, a root resource, a lone wolf"
    name = models.CharField(max_length=512)


class Namespace(models.Model):
    "Example of a child object with its own child objects"
    name = models.CharField(max_length=64, unique=True, blank=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='namespaces')


class CollectionImport(models.Model):
    "Example of a child of a child object, organization is implied by its namespace"
    name = models.CharField(max_length=64, unique=True, blank=False)
    namespace = models.ForeignKey(Namespace, on_delete=models.CASCADE, related_name='collections')


class ExampleEvent(models.Model):
    "Example of a model which is not registered in permission registry in the first place"
    name = models.CharField(max_length=64, unique=True, blank=False)


class Cow(models.Model):
    "This model has a special action it can do, which is to give advice"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='cows')

    class Meta:
        app_label = 'test_app'
        ordering = ['id']
        permissions = [('say_cow', 'Make cow say some advice')]


class UUIDModel(models.Model):
    "Tests that system works with a model that has a string uuid primary key"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='uuidmodels')


class AutoExtraUUIDModel(UUIDModel):
    """Adds more uniqueness to UUID, for use by any interdimensional travelers

    This model accomplishes that by using concrete inheritance,
    so the parent model is made automatically like
    AutoExtraUUIDModel.objects.create(organization=org)
    """

    extra_id = models.UUIDField(default=uuid.uuid4)


class ManualExtraUUIDModel(models.Model):
    """Extra-uniquene UUID made by manually feeding in a prior UUIDModel

    An example would be:
    ManualExtraUUIDModel.objects.create(organization=org)
    """

    uuidmodel_ptr = models.OneToOneField(UUIDModel, on_delete=models.CASCADE, editable=False, related_name="+", primary_key=True)
    extra_id = models.UUIDField(default=uuid.uuid4)


class ExtraExtraUUIDModel(models.Model):
    """In case the prior models were not unique enough, this adds another UUID"""

    extra_uuid = models.OneToOneField(ManualExtraUUIDModel, on_delete=models.CASCADE, editable=False, related_name="+", primary_key=True)
    third_id = models.UUIDField(default=uuid.uuid4)


class ImmutableTask(models.Model):
    "Hypothetical immutable task-like thing, can be created and canceled but not edited"

    class Meta:
        default_permissions = ('add', 'view', 'delete')
        ordering = ['id']
        permissions = [('cancel_immutabletask', 'Stop this task from running')]


class ParentName(models.Model):
    "Tests that system works with a parent field name different from parent model name"
    my_organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='parentnames')


class PositionModel(models.Model):
    "Uses a primary key other than id to test that everything still works"
    position = models.BigIntegerField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='positionmodels')


class WeirdPerm(models.Model):
    "Uses a weird permission name"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='weirdperms')

    class Meta:
        app_label = 'test_app'
        ordering = ['id']
        permissions = [("I'm a lovely coconut", "You can be a lovely coconut with this object"), ("crack", "Can crack open this coconut")]


class ProxyInventory(Inventory):
    "This is not a registered permissions model. It exposes issues with duplicate permission codenames."

    class Meta:
        proxy = True
        ordering = ['id']
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


class PublicData(NamedCommonModel):
    "Example of model with access controls for editing, but visible publically"

    class Meta:
        default_permissions = ('add', 'change', 'delete')  # does not list view
        ordering = ['id']

    data = models.JSONField(blank=True, null=False, default=dict)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='public_data')


permission_registry.register(Organization, Inventory, Credential, Namespace, Team, Cow, UUIDModel, PositionModel, WeirdPerm, PublicData)
permission_registry.register(ParentName, parent_field_name='my_organization')
permission_registry.register(CollectionImport, parent_field_name='namespace')
permission_registry.register(InstanceGroup, ImmutableTask, LogEntry, parent_field_name=None)
# Note that these polymorphic UUID models may not be useful in practice
# since permissions would be double-tracked on the sub-class table and the original UUIDModel table
permission_registry.register(AutoExtraUUIDModel, ManualExtraUUIDModel, parent_field_name='uuidmodel_ptr')
permission_registry.register(ExtraExtraUUIDModel, parent_field_name='extra_uuid')


# NOTE(cutwater): Using hard coded role names instead of ones defined in ReconcileUser class,
#   to avoid circular dependency between models and claims modules. This is a temporary workarond,
#   since we plan to drop support of tracked relationships in future.
permission_registry.track_relationship(Team, 'users', 'Team Member')
permission_registry.track_relationship(Team, 'admins', 'Team Admin')
permission_registry.track_relationship(Team, 'team_parents', 'Team Member')

permission_registry.track_relationship(Organization, 'users', 'Organization Member')
permission_registry.track_relationship(Organization, 'admins', 'Organization Admin')


class MultipleFieldsModel(NamedCommonModel):
    class Meta:
        app_label = "test_app"
        ordering = ['id']

    char_field1 = models.CharField(max_length=100, null=True, default='a')
    char_field2 = models.CharField(max_length=100, null=True, default='b')
    int_field = models.PositiveIntegerField(null=True, default=1)
    bool_field = models.BooleanField(default=True)


class Animal(NamedCommonModel, AuditableModel):
    class Meta:
        app_label = "test_app"
        ordering = ['id']

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
        ordering = ['id']

    activity_stream_limit_field_names = ['country']

    country = prevent_search(models.CharField(max_length=100, null=True, default='USA'))
    population = models.PositiveIntegerField(null=True, default=1000)
    extra_data = JSONField(null=True, default=dict)
    state = models.CharField(max_length=100, null=True, editable=False)


class SecretColor(AuditableModel):
    """
    An AuditableModel that also has encrypted fields.
    """

    class Meta:
        app_label = "test_app"

    encrypted_fields = ['color']

    color = models.CharField(max_length=20, null=True, default='blue')


class ThingSomeoneOwns(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=False, related_name="things_i_own")
    thing = models.CharField(max_length=256, null=False)

    class Meta:
        unique_together = (
            'owner',
            'thing',
        )


class ThingSomeoneShares(models.Model):
    owner = models.ManyToManyField(User, related_name="things_i_share")
    thing = models.CharField(max_length=256, null=False)
