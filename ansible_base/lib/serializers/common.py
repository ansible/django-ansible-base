import logging

from django.db.models.fields import NOT_PROVIDED
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.fields import empty
from rest_framework.serializers import ValidationError

from ansible_base.lib.abstract_models.common import get_url_for_object
from ansible_base.lib.serializers.validation import ValidationSerializerMixin
from ansible_base.lib.utils import models
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

logger = logging.getLogger('ansible_base.lib.serializers.common')


class AbstractCommonModelSerializer(ValidationSerializerMixin, serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField('_get_related')
    summary_fields = serializers.SerializerMethodField('_get_summary_fields')

    class Meta:
        fields = ['id', 'url', 'related', 'summary_fields']

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

    def get_url(self, obj) -> str:
        return get_url_for_object(obj)

    @property
    def is_list_view(self) -> bool:
        view = self.context.get('view')
        if view is None:
            raise ValueError("View not found in context")
        return view.action == 'list'

    # Type hints are used by OpenAPI
    def _get_related(self, obj) -> dict[str, str]:
        if obj is None:
            return {}
        related_fields = {}
        view = self.context.get('view')
        if view is not None and hasattr(view, 'extra_related_fields'):
            related_fields.update(view.extra_related_fields(obj))
        if not hasattr(obj, 'related_fields'):
            logger.warning(f"Object {obj.__class__} has no related_fields method")
        else:
            related_fields.update(obj.related_fields(self.context.get('request')))

        return related_fields

    def _get_summary_fields(self, obj) -> dict[str, dict]:
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


class CommonModelSerializer(AbstractCommonModelSerializer):
    class Meta(AbstractCommonModelSerializer.Meta):
        fields = AbstractCommonModelSerializer.Meta.fields + ['created', 'created_by', 'modified', 'modified_by']


class NamedCommonModelSerializer(CommonModelSerializer):
    class Meta(CommonModelSerializer.Meta):
        fields = CommonModelSerializer.Meta.fields + ['name']


class ImmutableCommonModelSerializer(AbstractCommonModelSerializer):
    class Meta(AbstractCommonModelSerializer.Meta):
        fields = AbstractCommonModelSerializer.Meta.fields + ['created', 'created_by']


class CommonUserSerializer(CommonModelSerializer):
    """
    Disallows editing of system user and enforces superuser requirement.
    """

    def validate(self, data):
        if models.get_system_user() is None:
            return data
        if hasattr(self, 'instance') and hasattr(self.instance, 'id') and self.instance.id == models.get_system_user().id:
            raise ValidationError(_('System users cannot be modified'))
        return data

    def validate_is_superuser(self, value):
        if value is True:
            if not self.context['request'].user.is_superuser:
                raise PermissionDenied
        return value
