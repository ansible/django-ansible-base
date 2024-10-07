from rest_framework import serializers

from ansible_base.features.models import Feature
from ansible_base.lib.abstract_models.common import get_url_for_object
from ansible_base.lib.serializers.validation import ValidationSerializerMixin


class FeatureSerializer(ValidationSerializerMixin, serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Feature
        fields = ['url', 'name', 'short_name', 'description', 'get_status_display', 'enabled', 'requires_restart']

    def get_url(self, obj) -> str:
        return get_url_for_object(obj)
