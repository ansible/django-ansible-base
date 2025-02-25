from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _
from oauth2_provider.generators import generate_client_secret

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.oauth2_provider.models import OAuth2Application


class OAuth2ApplicationSerializer(NamedCommonModelSerializer):
    oauth2_client_secret = None

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
            'app_url': {'label': _('Application URL')},
            'skip_authorization': {'label': _('Skip Authorization')},
        }

    def _get_client_secret(self, obj):
        request = self.context.get('request', None)
        try:
            if obj.client_type == 'public':
                return None
            elif request.method == 'POST':
                # Show the secret, one time, on POST
                return self.oauth2_client_secret
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
            ret['client_secret'] = secret
        return ret

    def _summary_field_tokens(self, obj):
        token_list = [{'id': x.pk, 'token': ENCRYPTED_STRING, 'scope': x.scope} for x in obj.access_tokens.all()[:10]]
        if len(token_list) < 10:
            token_count = len(token_list)
        else:
            token_count = obj.access_tokens.count()
        return {'count': token_count, 'results': token_list}

    def _get_summary_fields(self, obj) -> dict[str, dict]:
        ret = super()._get_summary_fields(obj)
        ret['tokens'] = self._summary_field_tokens(obj)
        return ret

    def create(self, validated_data):
        # This is hacky:
        # There is a cascading set of issues here.
        # 1. The first thing to know is that DOT automatically hashes the client_secret
        #    in a pre_save method on the client_secret field.
        # 2. In current released versions, there is no way to disable (1). It uses
        #    the built-in Django password hashing stuff to do this. There's a merged
        #    PR to allow disabling this (DOT #1311), but it's not released yet.
        # 3. If we use our own encrypted_field stuff, it conflicts with (1) and (2).
        #    They end up giving our encrypted field to Django's password check
        #    and *we* end up showing *their* hashed value to the user on POST, which
        #    doesn't work, the user needs to see the real (decrypted) value. So
        #    until upstream #1311 is released, we do NOT treat the field as an
        #    encrypted_field, we just defer to the upstream hashing.
        # 4. But we have no way to see the client_secret on POST, if we let the
        #    model generate it, because it's hashed by the time we get to the
        #    serializer...
        #
        # So to that end, on POST, we'll make the client secret here, and then
        # we can access it to show the user the value (once) on POST.
        validated_data['client_secret'] = generate_client_secret()
        self.oauth2_client_secret = validated_data['client_secret']
        return super().create(validated_data)
