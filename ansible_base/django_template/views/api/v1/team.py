from ansible_base.django_template.serializers import TeamSerializer
from ansible_base.django_template.views.api.v1.common import RoleModelViewSet
from ansible_base.lib.utils.auth import get_team_model


class TeamViewSet(RoleModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = get_team_model().objects.select_related("resource").all()
    serializer_class = TeamSerializer
