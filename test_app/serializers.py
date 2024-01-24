from rest_framework.serializers import ModelSerializer

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from test_app.models import EncryptionModel, User


class EncryptionTestSerializer(NamedCommonModelSerializer):
    reverse_url_name = None

    class Meta:
        model = EncryptionModel
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in EncryptionModel._meta.concrete_fields]


class UserSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'
