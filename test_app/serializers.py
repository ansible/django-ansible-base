from rest_framework.serializers import ModelSerializer

from ansible_base.lib.serializers.common import CommonModelSerializer, NamedCommonModelSerializer
from test_app import models


class OrganizationSerializer(NamedCommonModelSerializer):
    class Meta:
        model = models.Organization
        fields = '__all__'


class TeamSerializer(NamedCommonModelSerializer):
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


class InventorySerializer(ModelSerializer):
    class Meta:
        model = models.Inventory
        fields = '__all__'


class InstanceGroupSerializer(ModelSerializer):
    class Meta:
        model = models.InstanceGroup
        fields = '__all__'


class CowSerializer(ModelSerializer):
    class Meta:
        model = models.Cow
        fields = '__all__'


class UUIDModelSerializer(ModelSerializer):
    class Meta:
        model = models.UUIDModel
        fields = '__all__'
