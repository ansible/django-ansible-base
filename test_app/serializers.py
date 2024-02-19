from rest_framework.serializers import ModelSerializer

from ansible_base.lib.serializers.common import CommonModelSerializer, NamedCommonModelSerializer
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


class UserSerializer(ModelSerializer):
    class Meta:
        model = models.User
        exclude = (
            'user_permissions',
            'groups',
        )


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


class InventorySerializer(RelatedAccessMixin, ModelSerializer):
    class Meta:
        model = models.Inventory
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
