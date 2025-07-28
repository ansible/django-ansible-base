from rest_framework import serializers


class PasswordAuthenticatorSerializer(serializers.Serializer):
    """Serializer for password authenticator items in UI auth response."""

    name = serializers.CharField(read_only=True)


class SSOAuthenticatorSerializer(serializers.Serializer):
    """Serializer for SSO authenticator items in UI auth response."""

    name = serializers.CharField(read_only=True)
    login_url = serializers.URLField(read_only=True)
    type = serializers.CharField(read_only=True)


class UIAuthResponseSerializer(serializers.Serializer):
    """Serializer for UI authentication configuration response."""

    passwords = PasswordAuthenticatorSerializer(many=True, read_only=True)
    ssos = SSOAuthenticatorSerializer(many=True, read_only=True)
    show_login_form = serializers.BooleanField(read_only=True)
    login_redirect_override = serializers.CharField(allow_blank=True, read_only=True)
    custom_login_info = serializers.CharField(allow_blank=True, read_only=True)
    custom_logo = serializers.CharField(allow_blank=True, read_only=True)
    managed_cloud_install = serializers.BooleanField(read_only=True)
