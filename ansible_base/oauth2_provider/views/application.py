from django.db.models import Count, Prefetch
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.models import OAuth2Application
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from ansible_base.oauth2_provider.serializers import OAuth2ApplicationSerializer


class OAuth2ApplicationViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    queryset = OAuth2Application.objects.all()
    serializer_class = OAuth2ApplicationSerializer
    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]
    select_related_fields = ('organization', 'created_by', 'modified_by')

    def get_queryset(self):
        access_token_model = OAuth2Application._meta.get_field('access_tokens').related_model
        return (
            OAuth2Application.objects.select_related(*self.select_related_fields)
            .annotate(access_token_count=Count('access_tokens'))
            .prefetch_related(
                Prefetch(
                    'access_tokens',
                    queryset=access_token_model.objects.order_by('id')[:10],
                    to_attr='_access_tokens',
                )
            )
        )
