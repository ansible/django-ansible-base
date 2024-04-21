from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING, ansible_encryption
from ansible_base.oauth2_provider.models import OAuth2Application


def has_model_field_prefetched(obj, thing):
    # from awx.main.utils import has_model_field_prefetched
    pass


class OAuth2ApplicationSerializer(NamedCommonModelSerializer):
    class Meta:
        model = OAuth2Application
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in OAuth2Application._meta.concrete_fields]
        read_only_fields = ('client_id', 'client_secret')
        read_only_on_update_fields = ('user', 'authorization_grant_type')
        extra_kwargs = {
            'user': {'allow_null': True, 'required': False},
            'organization': {'allow_null': False},
            'authorization_grant_type': {'allow_null': False, 'label': _('Authorization Grant Type')},
            'client_secret': {'label': _('Client Secret')},
            'client_type': {'label': _('Client Type')},
            'redirect_uris': {'label': _('Redirect URIs')},
            'skip_authorization': {'label': _('Skip Authorization')},
        }

    def _get_client_secret(self, obj):
        request = self.context.get('request', None)
        try:
            if obj.client_type == 'public':
                return None
            elif request.method == 'POST':
                return ansible_encryption.decrypt_string(obj.client_secret)
            else:
                return ENCRYPTED_STRING
        except ObjectDoesNotExist:
            return ''

    def to_representation(self, instance):
        # We have to override this because in AbstractCommonModelSerializer, we'll
        # auto-force all encrypted fields to ENCRYPTED_STRING. Usually that's fine,
        # but we want to show the client_secret on POST. Ideally we'd just use
        # get_client_secret() and a SerializerMethodField.
        ret = super().to_representation(instance)
        secret = self._get_client_secret(instance)
        if secret is None:
            del ret['client_secret']
        else:
            ret['client_secret'] = self._get_client_secret(instance)
        return ret

    def _summary_field_tokens(self, obj):
        token_list = [{'id': x.pk, 'token': ENCRYPTED_STRING, 'scope': x.scope} for x in obj.oauth2accesstoken_set.all()[:10]]
        if has_model_field_prefetched(obj, 'oauth2accesstoken_set'):
            token_count = len(obj.oauth2accesstoken_set.all())
        else:
            if len(token_list) < 10:
                token_count = len(token_list)
            else:
                token_count = obj.oauth2accesstoken_set.count()
        return {'count': token_count, 'results': token_list}

    def get_summary_fields(self, obj):
        ret = super(OAuth2ApplicationSerializer, self).get_summary_fields(obj)
        ret['tokens'] = self._summary_field_tokens(obj)
        return ret
