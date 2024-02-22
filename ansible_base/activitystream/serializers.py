from ansible_base.activitystream.models import Entry
from ansible_base.lib.serializers.common import CommonModelSerializer


class EntrySerializer(CommonModelSerializer):
    class Meta:
        model = Entry
        fields = CommonModelSerializer.Meta.fields + ['operation', 'changes']
