from rest_framework import serializers

from .utils import get_django_flags


class FeatureFlagSerializer(serializers.Serializer):
    """Serialize list of feature flags"""

    def __init__(self, flag_name=None, *args, **kwargs):
        if flag_name == 'all':
            self.flag_name = None
        else:
            self.flag_name = flag_name
        super().__init__(None, *args, **kwargs)

    def to_representation(self) -> dict:
        return_data = {}
        feature_flags = get_django_flags()
        if self.flag_name:
            _flag_name = self.flag_name.upper()  # In case lower-case flag name is provided, convert to uppercase to ensure match
            if _flag_name in feature_flags:
                return_data[_flag_name] = feature_flags[_flag_name]
        else:
            return_data = feature_flags

        return return_data

    name = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
