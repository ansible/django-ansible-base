from ansible_base.lib.serializers.common import CommonModelSerializer
from ansible_base.activitystream.models import Entry

class EntrySerializer(CommonModelSerializer):
    class Meta:
        model = Entry
        fields = CommonModelSerializer.Meta.fields + ['operation', 'changes']
