from rest_framework import serializers


class FeatureFlagSerializer(serializers.Serializer):
    """Serialize list of feature flags"""

    name = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
