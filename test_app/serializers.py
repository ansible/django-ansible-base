from ansible_base.common.serializers.common import NamedCommonModelSerializer
from test_app.models import EncryptionModel


class EncryptionTestSerializer(NamedCommonModelSerializer):
    reverse_url_name = None

    class Meta:
        model = EncryptionModel
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in EncryptionModel._meta.concrete_fields]
