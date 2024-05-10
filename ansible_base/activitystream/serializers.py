import logging
from copy import deepcopy
from typing import Optional

from rest_framework import serializers

from ansible_base.activitystream.models import Entry
from ansible_base.lib.abstract_models.common import CreatableModel, get_url_for_object
from ansible_base.lib.serializers.common import ImmutableCommonModelSerializer

logger = logging.getLogger('ansible_base.activitystream.serializers')


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

    def get_content_type_model(self, obj) -> Optional[str]:
        if obj.content_type:
            return obj.content_type.model

    def get_related_content_type_model(self, obj) -> Optional[str]:
        if obj.related_content_type:
            return obj.related_content_type.model

    def _field_value_to_python(self, entry, field_name, value):
        model = entry.content_type.model_class()
        if model is None:
            # If the model was deleted, we lose the ability to convert the
            # field back to the correct type, because we don't know what the
            # field was. We'll just return the value as is and keep it as a
            # string. This is kind of a gross edge case.
            return value
        field = model._meta.get_field(field_name)
        return field.to_python(value)

    def get_changes(self, obj) -> Optional[dict[str, dict]]:
        """
        We store strings, we have to convert them back to the correct type.
        Related associations and disassociations will show a null for changes.
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
        if self.is_list_view:
            return summary_fields

        try:
            if obj.content_object is not None and hasattr(obj.content_object, 'summary_fields'):
                summary_fields['content_object'] = obj.content_object.summary_fields()
        except AttributeError:  # Likely the model was deleted
            pass

        try:
            if obj.related_content_object is not None and hasattr(obj.related_content_object, 'summary_fields'):
                summary_fields['related_content_object'] = obj.related_content_object.summary_fields()
        except AttributeError:  # Likely the model was deleted
            pass

        if obj.changes is None:
            return summary_fields

        changed_fk_fields = obj.changed_fk_fields

        for field_name, (related_model, pk) in changed_fk_fields.items():
            if related_object := related_model.objects.filter(pk=pk).first():
                if hasattr(related_object, 'summary_fields'):
                    summary_fields[f"changes.{field_name}"] = related_object.summary_fields()

        return summary_fields

    def _get_related(self, obj) -> dict[str, str]:
        fields = super()._get_related(obj)

        if self.is_list_view:
            return fields

        # content_object
        try:
            if obj.content_object is not None:
                fields['content_object'] = get_url_for_object(obj.content_object)
        except AttributeError:  # Likely the model was deleted
            pass

        # related_content_object
        try:
            if obj.related_content_object is not None:
                fields['related_content_object'] = get_url_for_object(obj.related_content_object)
        except AttributeError:  # Likely the model was deleted
            pass

        for field_name, (related_model, pk) in obj.changed_fk_fields.items():
            if related_object := related_model.objects.filter(pk=pk).first():
                # If the related object inherits CreatableModel, we can check and make sure it's
                # older than the activity stream entry. If it's not, then we don't want to link to it.
                if isinstance(related_object, CreatableModel) and related_object.created > obj.created:
                    model = obj.content_type.model_class()
                    logger.warning(
                        f"Refusing to relate {related_object} to activity stream entry for {model} {obj.object_id} because it was created after the entry"
                    )
                    continue

                if related_url := get_url_for_object(related_object, pk=pk):
                    fields[f"changes.{field_name}"] = related_url

        return fields
