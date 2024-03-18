from ansible_base.activitystream.models import Entry
from ansible_base.lib.serializers.common import ImmutableCommonModelSerializer


class EntrySerializer(ImmutableCommonModelSerializer):
    class Meta:
        model = Entry
        fields = ImmutableCommonModelSerializer.Meta.fields + ['operation', 'changes']
