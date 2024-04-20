from django.utils.translation import gettext_lazy as _

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING, ansible_encryption
from ansible_base.oauth2_provider.models import OAuth2Application


def has_model_field_prefetched(obj, thing):
    # from awx.main.utils import has_model_field_prefetched
    pass


class OAuth2ApplicationSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'application-detail'

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

    def to_representation(self, obj):
        ret = super(OAuth2ApplicationSerializer, self).to_representation(obj)
        request = self.context.get('request', None)
        if request and request.method == 'POST':
            # Only return the (decrypted) client_secret on the initial create
            ret['client_secret'] = ansible_encryption.decrypt_string(obj.client_secret)
        if obj.client_type == 'public':
            ret.pop('client_secret', None)
        return ret

    def get_related(self, obj):
        res = super(OAuth2ApplicationSerializer, self).get_related(obj)
        res.update(
            dict(
                tokens=self.reverse('api:o_auth2_application_token_list', kwargs={'pk': obj.pk}),
                activity_stream=self.reverse('api:o_auth2_application_activity_stream_list', kwargs={'pk': obj.pk}),
            )
        )
        if obj.organization_id:
            res.update(
                dict(
                    organization=self.reverse('api:organization_detail', kwargs={'pk': obj.organization_id}),
                )
            )
        return res

    def get_modified(self, obj):
        if obj is None:
            return None
        return obj.updated

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
