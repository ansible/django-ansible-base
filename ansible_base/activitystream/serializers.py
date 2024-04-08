from rest_framework import serializers

from ansible_base.activitystream.models import Entry
from ansible_base.lib.serializers.common import ImmutableCommonModelSerializer


class EntrySerializer(ImmutableCommonModelSerializer):
    class Meta:
        model = Entry
        fields = ImmutableCommonModelSerializer.Meta.fields + [
            'operation',
            'changes',
            'content_type',
            'object_id',
            'related_content_type',
            'related_object_id',
            'content_type_model',
            'related_content_type_model',
        ]

    content_type_model = serializers.SerializerMethodField()
    related_content_type_model = serializers.SerializerMethodField()

    def get_content_type_model(self, obj):
        if obj.content_type:
            return obj.content_type.model

    def get_related_content_type_model(self, obj):
        if obj.related_content_type:
            return obj.related_content_type.model

    def _get_summary_fields(self, obj) -> dict[str, dict]:
        summary_fields = super()._get_summary_fields(obj)

        content_obj = obj.content_object
        if content_obj and hasattr(content_obj, 'summary_fields'):
            summary_fields['content_object'] = content_obj.summary_fields()

        related_content_obj = obj.related_content_object
        if related_content_obj and hasattr(related_content_obj, 'summary_fields'):
            summary_fields['related_content_object'] = related_content_obj.summary_fields()

        return summary_fields
