from flags.state import flag_state
from rest_framework import serializers

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from .utils import get_django_flags


class FeatureFlagSerializer(NamedCommonModelSerializer):
    """Serialize list of feature flags"""

    state = serializers.SerializerMethodField()

    class Meta:
        model = AAPFlag
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in AAPFlag._meta.concrete_fields] + ['state']
        read_only_fields = ["name", "condition", "required", "support_level", "visibility", "toggle_type", "description", "labels", "ui_name", "support_url"]

    def get_state(self, instance):
        return flag_state(instance.name)

    def to_representation(self, instance):
        instance.state = True
        ret = super().to_representation(instance)
        return ret


# TODO: Remove once all components are migrated to the new endpont.
class OldFeatureFlagSerializer(NamedCommonModelSerializer):
    """Serialize list of feature flags"""

    class Meta:
        model = AAPFlag
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in AAPFlag._meta.concrete_fields]
        read_only_fields = ["name", "condition", "required", "support_level", "visibility", "toggle_type", "description", "labels"]

    def to_representation(self, instance=None) -> dict:
        return_data = {}
        feature_flags = get_django_flags()
        for feature_flag in feature_flags:
            return_data[feature_flag] = flag_state(feature_flag)
        return return_data
