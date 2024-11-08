# from rest_framework import serializers
from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.rbac.api.related import RelatedAccessMixin


class TeamSerializer(RelatedAccessMixin, NamedCommonModelSerializer):
    lookup_field = 'users'

    class Meta:
        model = get_team_model()
        fields = NamedCommonModelSerializer.Meta.fields + [
            'organization',
            'description',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request:
            self.fields['organization'].queryset = get_organization_model().access_qs(request.user)

    def get_extra_kwargs(self):
        extra_kwargs = super().get_extra_kwargs()
        request = self.context.get('request')
        if request and request.user.is_superuser:
            return extra_kwargs

        view = self.context.get('view')
        if view:
            action = view.action

            if action in ['create', 'update', 'partial_update']:
                kwargs = extra_kwargs.get('organization')
                kwargs['read_only'] = action in ['update', 'partial_update']
                extra_kwargs['organization'] = kwargs

        return extra_kwargs
