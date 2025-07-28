from rest_framework import serializers


class PasswordAuthenticatorSerializer(serializers.Serializer):
    """Serializer for password authenticator items in UI auth response."""

    name = serializers.CharField()


class SSOAuthenticatorSerializer(serializers.Serializer):
    """Serializer for SSO authenticator items in UI auth response."""

    name = serializers.CharField()
    login_url = serializers.URLField()
    type = serializers.CharField()


class UIAuthResponseSerializer(serializers.Serializer):
    """Serializer for UI authentication configuration response."""

    passwords = PasswordAuthenticatorSerializer(many=True)
    ssos = SSOAuthenticatorSerializer(many=True)
    show_login_form = serializers.BooleanField()
    login_redirect_override = serializers.CharField(allow_blank=True)
    custom_login_info = serializers.CharField(allow_blank=True)
    custom_logo = serializers.CharField(allow_blank=True)
    managed_cloud_install = serializers.BooleanField()
