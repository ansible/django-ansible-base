import logging

from rest_framework import serializers
from rest_framework.reverse import reverse_lazy

from ansible_base.utils.encryption import ENCRYPTED_STRING

logger = logging.getLogger('ansible_base.serializers')


class CommonModelSerializer(serializers.ModelSerializer):
    show_capabilities = ['edit', 'delete']
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField('_get_related')
    summary_fields = serializers.SerializerMethodField('_get_summary_fields')

    class Meta:
        fields = ['id', 'url', 'created_on', 'created_by', 'modified_on', 'modified_by', 'related', 'summary_fields']

    def get_url(self, obj):
        if self.reverse_url_name:
            return reverse_lazy(self.reverse_url_name, kwargs={'pk': obj.pk})
        return ''

    def _get_related(self, obj):
        if obj is None:
            return {}
        if not hasattr(obj, 'related_fields'):
            logger.warning(f"Object {obj.__class__} has no related_fields method")
            return {}
        return obj.related_fields(self.context.get('request'))

    def _get_summary_fields(self, obj):
        if obj is None:
            return {}
        if not hasattr(obj, 'get_summary_fields'):
            logger.warning(f"Object {obj.__class__} has no get_summary_fields method")
            return {}
        return obj.get_summary_fields()

    def to_representation(self, obj):
        ret = super().to_representation(obj)

        for key in obj.encrypted_fields:
            if key in ret:
                ret[key] = ENCRYPTED_STRING

        return ret

    def update(self, instance, validated_data):
        # We don't want the $encrypted$ fields going back to the model
        for key in self.Meta.model.encrypted_fields:
            new_field = validated_data.get(key, None)
            if new_field and new_field == ENCRYPTED_STRING:
                validated_data.pop(key, None)

        return super().update(instance, validated_data)


class NamedCommonModelSerializer(CommonModelSerializer):
    class Meta(CommonModelSerializer.Meta):
        fields = [
            'name',
        ] + CommonModelSerializer.Meta.fields
