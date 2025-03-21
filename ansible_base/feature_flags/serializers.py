from flags.state import flag_state

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from .utils import get_django_flags


class FeatureFlagSerializer(NamedCommonModelSerializer):
    """Serialize list of feature flags"""

    class Meta:
        model = AAPFlag
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in AAPFlag._meta.concrete_fields]
        read_only_fields = ["name", "condition", "required", "support_level", "visibility", "toggle_type", "description", "version_added", "labels"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        return ret


# TODO: Remove once all components are migrated to the new endpont.
class OldFeatureFlagSerializer(NamedCommonModelSerializer):
    """Serialize list of feature flags"""

    class Meta:
        model = AAPFlag
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in AAPFlag._meta.concrete_fields]
        read_only_fields = ["name", "condition", "required", "support_level", "visibility", "toggle_type", "description", "version_added", "labels"]

    def to_representation(self) -> dict:
        return_data = {}
        feature_flags = get_django_flags()
        for feature_flag in feature_flags:
            return_data[feature_flag] = flag_state(feature_flag)
        return return_data
