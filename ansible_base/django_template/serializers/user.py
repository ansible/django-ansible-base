import logging

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.fields import empty

from ansible_base.django_template.models.user import password_is_usable
from ansible_base.lib.serializers.common import CommonUserSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

logger = logging.getLogger('aap.gateway.serializer.user')

PASSWORD_DISABLED = 'Password Disabled'  # signal unusable passwords


class UserSerializer(CommonUserSerializer):
    password = serializers.CharField(required=False, max_length=128, allow_blank=True)

    def __init__(self, instance=None, data=empty, **kwargs):
        super().__init__(instance, data, **kwargs)

    class Meta(CommonUserSerializer.Meta):
        model = get_user_model()
        fields = CommonUserSerializer.Meta.fields + [
            'username',
            'email',
            'first_name',
            'last_name',
            'last_login',
            'password',
            'is_superuser',
            'managed',
        ]
        read_only_fields = ["last_login"]

    def update(self, instance, validated_data):
        # We don't want the $encrypted$ password going back to the model
        if validated_data.get('password', "") in [ENCRYPTED_STRING, PASSWORD_DISABLED]:
            validated_data.pop('password', None)

        instance = super().update(instance, validated_data)

        return instance

    def to_representation(self, obj):
        ret = super(UserSerializer, self).to_representation(obj)
        if password_is_usable(ret['password']):
            # If its an internal account lets assume there is a password and return a masked value to the user
            ret['password'] = ENCRYPTED_STRING
        else:
            # User does not have a local password, or password is unusable/ disabled
            ret['password'] = PASSWORD_DISABLED

        return ret
