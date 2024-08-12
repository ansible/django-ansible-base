import logging

from django.contrib.contenttypes.models import ContentType

from ansible_base.jwt_consumer.common.auth import JWTAuthentication
from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.resource_registry.models import Resource

logger = logging.getLogger('ansible_base.jwt_consumer.hub.auth')


class HubJWTAuth(JWTAuthentication):
    def process_permissions(self):
        # Map teams in the JWT to Automation Hub groups.
        try:
            from galaxy_ng.app.models import Organization, Team
            from pulpcore.plugin.util import assign_role, remove_role

            self.team_content_type = ContentType.objects.get_for_model(Team)
            self.org_content_type = ContentType.objects.get_for_model(Organization)
        except ImportError:
            raise InvalidService("automation-hub")

        teams = []
        groups = []
        for role_name in self.common_auth.token.get('object_roles', {}).keys():
            if role_name.startswith('Team'):
                for object_index in self.common_auth.token['object_roles'][role_name]['objects']:
                    team_data = self.common_auth.token['objects']['team'][object_index]
                    ansible_id = team_data['ansible_id']
                    try:
                        team = Resource.objects.get(ansible_id=ansible_id).content_object
                    except Resource.DoesNotExist:
                        team = self.common_auth.get_or_create_resource('team', team_data)[1]
                    teams.append(team)

                    groups.append(team.group)

        self.common_auth.user.groups.set(groups)

        # manage team membership ...
        team_pks = [team.pk for team in teams]
        for team in Team.objects.exclude(pk__in=team_pks).filter(users=self.common_auth.user):
            team.users.remove(self.common_auth.user)
        for team in teams:
            team.users.add(self.common_auth.user)

        if "Platform Auditor" in self.common_auth.token.get('global_roles', []):
            assign_role("galaxy.auditor", self.common_auth.user)
        else:
            remove_role("galaxy.auditor", self.common_auth.user)
