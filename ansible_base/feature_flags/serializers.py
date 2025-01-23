from rest_framework import serializers


class FeatureFlagSerializer(serializers.Serializer):
    """Serialize list of feature flags"""

    def __init__(self, flag_name=None, *args, **kwargs):
        if flag_name == 'all':
            self.flag_name = None
        else:
            self.flag_name = flag_name
        super().__init__(None, *args, **kwargs)
