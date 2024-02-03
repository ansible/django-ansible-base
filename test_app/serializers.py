from rest_framework.serializers import ModelSerializer

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from test_app import models


class OrganizationSerializer(NamedCommonModelSerializer):
    class Meta:
        model = models.Organization
        fields = '__all__'


class TeamSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'team-detail'

    class Meta:
        model = models.Team
        fields = '__all__'


class UserSerializer(ModelSerializer):
    class Meta:
        model = models.User
        fields = '__all__'


class EncryptionTestSerializer(NamedCommonModelSerializer):
    reverse_url_name = None

    class Meta:
        model = models.EncryptionModel
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in models.EncryptionModel._meta.concrete_fields]
