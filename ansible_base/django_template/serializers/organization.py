from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.utils.auth import get_organization_model


class OrganizationSerializer(NamedCommonModelSerializer):
    class Meta:
        model = get_organization_model()
        fields = NamedCommonModelSerializer.Meta.fields + [
            'description',
            'managed',
        ]
