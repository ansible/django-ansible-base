from rest_framework.exceptions import PermissionDenied
from rest_framework.serializers import ModelSerializer

from ansible_base.lib.serializers.common import CommonModelSerializer, ImmutableCommonModelSerializer, NamedCommonModelSerializer
from ansible_base.rbac.api.related import RelatedAccessMixin
from test_app import models


class OrganizationSerializer(RelatedAccessMixin, NamedCommonModelSerializer):
    class Meta:
        model = models.Organization
        fields = '__all__'


class TeamSerializer(RelatedAccessMixin, NamedCommonModelSerializer):
    class Meta:
        model = models.Team
        fields = '__all__'


class UserSerializer(CommonModelSerializer):
    class Meta:
        model = models.User
        exclude = (
            'user_permissions',
            'groups',
        )

    def validate_is_superuser(self, value):
        if value is True:
            if not self.context['request'].user.is_superuser:
                raise PermissionDenied
        return value


class EncryptionModelSerializer(NamedCommonModelSerializer):
    class Meta:
        model = models.EncryptionModel
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in models.EncryptionModel._meta.concrete_fields]


class RelatedFieldsTestModelSerializer(CommonModelSerializer):
    class Meta:
        model = models.RelatedFieldsTestModel
        fields = '__all__'


class ResourceMigrationTestModelSerializer(CommonModelSerializer):
    class Meta:
        model = models.ResourceMigrationTestModel
        fields = '__all__'


class MultipleFieldsModelSerializer(NamedCommonModelSerializer):
    class Meta:
        model = models.MultipleFieldsModel
        fields = '__all__'


class AnimalSerializer(NamedCommonModelSerializer):
    class Meta:
        model = models.Animal
        fields = '__all__'


class InventorySerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.Inventory
        fields = '__all__'


class NamespaceSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.Namespace
        fields = '__all__'


class CollectionImportSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.CollectionImport
        fields = '__all__'


class ParentNameSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.ParentName
        fields = '__all__'


class PositionModelSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.PositionModel
        fields = '__all__'


class WeirdPermSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.WeirdPerm
        fields = '__all__'


class InstanceGroupSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.InstanceGroup
        fields = '__all__'


class CowSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.Cow
        fields = '__all__'


class UUIDModelSerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.UUIDModel
        fields = '__all__'


class ImmutableLogEntrySerializer(ImmutableCommonModelSerializer):
    class Meta:
        model = models.ImmutableLogEntry
        fields = '__all__'


class CitySerializer(NamedCommonModelSerializer):
    class Meta:
        model = models.City
        fields = '__all__'
