from rest_framework import serializers

from .utils import get_django_flags


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
        feature_flags = get_django_flags()
        if self.category_slug:
            flag_name = self.category_slug.upper()  # In case lower-case flag name is provided, convert to uppercase to ensure match
            if flag_name in feature_flags:
                return_data[flag_name] = feature_flags[flag_name]
        else:
            return_data = feature_flags

        return return_data

    name = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
