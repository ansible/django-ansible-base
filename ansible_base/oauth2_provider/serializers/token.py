import logging
from datetime import timedelta
from typing import Optional

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
from ansible_base.oauth2_provider.models.access_token import SCOPES

logger = logging.getLogger("ansible_base.oauth2_provider.serializers.token")


class OAuth2TokenSerializer(CommonModelSerializer):
    refresh_token = SerializerMethodField()

    unencrypted_token = None  # Only used in POST so we can return the token in the response
    unencrypted_refresh_token = None  # Only used in POST so we can return the refresh token in the response

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

    def to_representation(self, instance):
        request = self.context.get('request', None)
        ret = super().to_representation(instance)
        if request and request.method == 'POST':
            # If we're creating the token, show it. Otherwise, show the encrypted string.
            ret['token'] = self.unencrypted_token
        else:
            ret['token'] = ENCRYPTED_STRING
        return ret

    def get_refresh_token(self, obj) -> Optional[str]:
        request = self.context.get('request')
        try:
            if not obj.refresh_token:
                return None
            elif request and request.method == 'POST':
                return self.unencrypted_refresh_token
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
            if word not in SCOPES:
                return False
        return True

    def validate_scope(self, value):
        if not self._is_valid_scope(value):
            raise ValidationError(_('Must be a simple space-separated string with allowed scopes {}.').format(SCOPES))
        return value

    def create(self, validated_data):
        current_user = get_current_user()
        validated_data['token'] = generate_token()
        expires_delta = get_setting('OAUTH2_PROVIDER', {}).get('ACCESS_TOKEN_EXPIRE_SECONDS', 0)
        if expires_delta == 0:
            logger.warning("OAUTH2_PROVIDER.ACCESS_TOKEN_EXPIRE_SECONDS was set to 0, creating token that has already expired")
        validated_data['expires'] = now() + timedelta(seconds=expires_delta)
        validated_data['user'] = self.context['request'].user
        self.unencrypted_token = validated_data.get('token')  # Before it is hashed

        try:
            obj = super().create(validated_data)
        except AccessDeniedError as e:
            raise PermissionDenied(str(e))

        if obj.application and obj.application.user:
            obj.user = obj.application.user
        obj.save()
        if obj.application:
            self.unencrypted_refresh_token = generate_token()
            OAuth2RefreshToken.objects.create(
                user=current_user,
                token=self.unencrypted_refresh_token,
                application=obj.application,
                access_token=obj,
            )
        return obj
