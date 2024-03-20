import logging

from django.db.models.fields import NOT_PROVIDED
from rest_framework import serializers
from rest_framework.fields import empty

from ansible_base.lib.abstract_models.common import get_url_for_object
from ansible_base.lib.serializers.validation import ValidationSerializerMixin
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

logger = logging.getLogger('ansible_base.lib.serializers.common')


COMMON_FIELDS = ('id', 'url', 'created', 'created_by', 'modified', 'modified_by', 'related', 'summary_fields')


class CommonModelSerializer(ValidationSerializerMixin, serializers.ModelSerializer):
    url = serializers.SerializerMethodField(read_only=True)
    related = serializers.SerializerMethodField('_get_related', read_only=True)
    summary_fields = serializers.SerializerMethodField('_get_summary_fields', read_only=True)

    class Meta:
        fields = COMMON_FIELDS

    def __init__(self, instance=None, data=empty, **kwargs):
        # pre-populate the form with the defaults from the model
        model = getattr(self.Meta, 'model', None)
        if model:
            extra_kwargs = getattr(self.Meta, 'extra_kwargs', {})
            for field in model._meta.concrete_fields:
                if field.name not in extra_kwargs:
                    extra_kwargs[field.name] = {}
                if not extra_kwargs[field.name].get('initial', None):
                    if field.default and field.default is not NOT_PROVIDED:
                        extra_kwargs[field.name]['initial'] = field.default
            setattr(self.Meta, 'extra_kwargs', extra_kwargs)
        super().__init__(instance, data, **kwargs)

    def get_url(self, obj):
        return get_url_for_object(obj)

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
        fields = ['name'] + list(COMMON_FIELDS)
