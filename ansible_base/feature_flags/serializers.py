from flags.state import flag_state
from rest_framework import serializers

from .utils import get_django_flags


class FeatureFlagSerializer(serializers.Serializer):
    """Serialize list of feature flags"""

    def to_representation(self) -> dict:
        return_data = {}
        feature_flags = get_django_flags()
        for feature_flag in feature_flags:
            return_data[feature_flag] = flag_state(feature_flag)

        return return_data
