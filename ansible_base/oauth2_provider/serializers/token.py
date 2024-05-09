import logging
from datetime import timedelta

from crum import get_current_user
from django.core.exceptions import ObjectDoesNotExist
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from oauthlib.common import generate_token
from oauthlib.oauth2 import AccessDeniedError
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.serializers import SerializerMethodField

from ansible_base.lib.serializers.common import CommonModelSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.settings import get_setting
from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken

logger = logging.getLogger("ansible_base.oauth2_provider.serializers.token")


class BaseOAuth2TokenSerializer(CommonModelSerializer):
    refresh_token = SerializerMethodField()
    token = SerializerMethodField()
    ALLOWED_SCOPES = [x[0] for x in OAuth2AccessToken.SCOPE_CHOICES]

    class Meta:
        model = OAuth2AccessToken
        fields = CommonModelSerializer.Meta.fields + [x.name for x in OAuth2AccessToken._meta.concrete_fields] + ['refresh_token']
        # The source_refresh_token and id_token are the concrete field but we change them to just token and refresh_token
        # We wrap these in a try for when we need to make the initial models
        try:
            fields.remove('source_refresh_token')
        except ValueError:
            pass
        try:
            fields.remove('id_token')
        except ValueError:
            pass
        read_only_fields = ('user', 'token', 'expires', 'refresh_token')
        extra_kwargs = {'scope': {'allow_null': False, 'required': False}, 'user': {'allow_null': False, 'required': True}}

    def get_token(self, obj):
        request = self.context.get('request')
        try:
            if request and request.method == 'POST':
                return obj.token
            else:
                return ENCRYPTED_STRING
        except ObjectDoesNotExist:
            return ''

    def get_refresh_token(self, obj):
        request = self.context.get('request')
        try:
            if not obj.refresh_token:
                return None
            elif request and request.method == 'POST':
                return getattr(obj.refresh_token, 'token', '')
            else:
                return ENCRYPTED_STRING
        except ObjectDoesNotExist:
            return None

    def _is_valid_scope(self, value):
        if not value or (not isinstance(value, str)):
            return False
        words = value.split()
        for word in words:
            if words.count(word) > 1:
                return False  # do not allow duplicates
            if word not in self.ALLOWED_SCOPES:
                return False
        return True

    def validate_scope(self, value):
        if not self._is_valid_scope(value):
            raise ValidationError(_('Must be a simple space-separated string with allowed scopes {}.').format(self.ALLOWED_SCOPES))
        return value

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        try:
            return super().create(validated_data)
        except AccessDeniedError as e:
            raise PermissionDenied(str(e))


class OAuth2TokenSerializer(BaseOAuth2TokenSerializer):
    def create(self, validated_data):
        current_user = get_current_user()
        validated_data['token'] = generate_token()
        expires_delta = get_setting('OAUTH2_PROVIDER', {}).get('ACCESS_TOKEN_EXPIRE_SECONDS', 0)
        if expires_delta == 0:
            logger.warning("OAUTH2_PROVIDER.ACCESS_TOKEN_EXPIRE_SECONDS was set to 0, creating token that has already expired")
        validated_data['expires'] = now() + timedelta(seconds=expires_delta)
        obj = super().create(validated_data)
        if obj.application and obj.application.user:
            obj.user = obj.application.user
        obj.save()
        if obj.application:
            OAuth2RefreshToken.objects.create(user=current_user, token=generate_token(), application=obj.application, access_token=obj)
        return obj
