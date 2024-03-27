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


class ImmutableLogEntrySerializer(ImmutableCommonModelSerializer):
    class Meta:
        model = models.ImmutableLogEntry
        fields = '__all__'
