from copy import deepcopy

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
    changes = serializers.SerializerMethodField()

    def get_content_type_model(self, obj):
        if obj.content_type:
            return obj.content_type.model

    def get_related_content_type_model(self, obj):
        if obj.related_content_type:
            return obj.related_content_type.model

    def _field_value_to_python(self, entry, field_name, value):
        model = entry.content_type.model_class()
        field = model._meta.get_field(field_name)
        return field.to_python(value)

    def get_changes(self, obj):
        """
        We store strings, we have to convert them back to the correct type.
        """
        if not obj.changes:
            return None

        changes = deepcopy(obj.changes)
        # We'll have 'added_fields', 'removed_fields', 'changed_fields'. The first two
        # are simple k-v pairs, the last is a k-v pair where the value is [old, new].
        for field_name, value in obj.changes['added_fields'].items():
            changes['added_fields'][field_name] = self._field_value_to_python(obj, field_name, value)
        for field_name, value in obj.changes['removed_fields'].items():
            changes['removed_fields'][field_name] = self._field_value_to_python(obj, field_name, value)
        for field_name, value in obj.changes['changed_fields'].items():
            changes['changed_fields'][field_name] = [
                self._field_value_to_python(obj, field_name, value[0]),
                self._field_value_to_python(obj, field_name, value[1]),
            ]
        return changes

    def _get_summary_fields(self, obj) -> dict[str, dict]:
        summary_fields = super()._get_summary_fields(obj)

        content_obj = obj.content_object
        if content_obj and hasattr(content_obj, 'summary_fields'):
            summary_fields['content_object'] = content_obj.summary_fields()

        related_content_obj = obj.related_content_object
        if related_content_obj and hasattr(related_content_obj, 'summary_fields'):
            summary_fields['related_content_object'] = related_content_obj.summary_fields()

        return summary_fields
