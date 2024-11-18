from flags.state import disable_flag, enable_flag, flag_enabled
from rest_framework import serializers

from .utils import get_feature_flags


class FeatureFlagSerializer(serializers.Serializer):
    """Serialize list of feature flags"""

    def __init__(self, category_slug=None, *args, **kwargs):
        if category_slug == 'all':
            self.category_slug = None
        else:
            self.category_slug = category_slug
        super().__init__(None, *args, **kwargs)

    def to_representation(self) -> dict:
        return_data = {}
        feature_flags = get_feature_flags()
        if self.category_slug:
            if self.category_slug in feature_flags:
                return_data[self.category_slug] = flag_enabled(self.category_slug)
        else:
            return_data = feature_flags

        return return_data

    def validate_and_save(self, data: dict) -> dict:
        if not self.category_slug:
            return {}
        if not isinstance(data[self.category_slug], bool):
            return {}
        feature_flags = get_feature_flags()
        if self.category_slug not in feature_flags:
            return {}

        if flag_enabled(self.category_slug) != data[self.category_slug]:
            if data[self.category_slug]:
                enable_flag(self.category_slug)
            else:
                disable_flag(self.category_slug)

        return self.to_representation()

    name = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
