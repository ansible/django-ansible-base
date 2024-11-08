from django.contrib.auth import get_user_model
from django.db.models.functions import Cast
from django.http import Http404

from ansible_base.django_template.serializers import OrganizationSerializer, TeamSerializer
from ansible_base.django_template.views.api.v1.common import TemplatedAppModelViewSet
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.models import ObjectRole
from ansible_base.rbac.policies import visible_users


class UserTeamViewSet(TemplatedAppModelViewSet):
    model = get_team_model
    serializer_class = TeamSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    def get_queryset(self):
        try:
            user = visible_users(self.request.user).get(pk=self.kwargs['pk'])
            return get_team_model().access_qs(user, 'member')
        except get_user_model.DoesNotExist:
            raise Http404("No User matches the given query")


class UserOrganizationViewSet(TemplatedAppModelViewSet):
    model = get_organization_model()
    serializer_class = OrganizationSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    def get_queryset(self):
        try:
            user = visible_users(self.request.user).get(pk=self.kwargs['pk'])
            return get_organization_model().objects.filter(
                id__in=ObjectRole.objects.filter(
                    role_definition__name__in=(get_organization_model().member_rd_name, get_organization_model().admin_rd_name), users=user.id
                ).values_list(Cast('object_id', output_field=get_organization_model()._meta.pk))
            )
        except get_user_model.DoesNotExist:
            raise Http404("No User matches the given query")
