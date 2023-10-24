import logging

from rest_framework import serializers
from rest_framework.reverse import reverse_lazy

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


class NamedCommonModelSerializer(CommonModelSerializer):
    class Meta(CommonModelSerializer.Meta):
        fields = [
            'name',
        ] + CommonModelSerializer.Meta.fields
