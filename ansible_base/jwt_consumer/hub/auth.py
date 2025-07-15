import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.query import IntegrityError

from ansible_base.jwt_consumer.common.auth import JWTAuthentication
from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from ansible_base.resource_registry.models import Resource

logger = logging.getLogger('ansible_base.jwt_consumer.hub.auth')


class HubJWTAuth(JWTAuthentication):

    def get_galaxy_models(self):
        '''This is separate from process_permissions purely for testability.'''
        try:
            from galaxy_ng.app.models import Organization, Team
        except ImportError:
            raise InvalidService("automation-hub")

        return Organization, Team

    def process_permissions(self):
        # Map teams in the JWT to Automation Hub groups.
        Organization, Team = self.get_galaxy_models()
        self.team_content_type = ContentType.objects.get_for_model(Team)
        self.org_content_type = ContentType.objects.get_for_model(Organization)

        # TODO - galaxy does not have an org admin roledef yet
        # admin_orgs = []

        # TODO - galaxy does not have an org member roledef yet
        # member_orgs = []

        # The "shared" [!local] teams this user admins
        admin_teams = []

        # the teams this user should have a "shared" [!local] assignment to
        member_teams = []

        for role_name in self.common_auth.token.get('object_roles', {}).keys():
            if role_name.startswith('Team'):
                for object_index in self.common_auth.token['object_roles'][role_name]['objects']:
                    team_data = self.common_auth.token['objects']['team'][object_index]
                    ansible_id = team_data['ansible_id']
                    try:
                        team = Resource.objects.get(ansible_id=ansible_id).content_object
                    except Resource.DoesNotExist:
                        try:
                            team = self.common_auth.get_or_create_resource('team', team_data)[1]
                        except IntegrityError as e:
                            logger.warning(
                                f"Got integrity error ({e}) on {team_data}. Skipping team assignment. "
                                "Please make sure the sync task is running to prevent this warning in the future."
                            )
                            continue

                    if role_name == 'Team Admin':
                        admin_teams.append(team)
                    elif role_name == 'Team Member':
                        member_teams.append(team)

        for roledef_name, teams in [('Team Admin', admin_teams), ('Team Member', member_teams)]:

            # the "shared" "non-local" definition ...
            roledef = RoleDefinition.objects.get(name=roledef_name)

            # pks for filtering ...
            team_pks = [team.pk for team in teams]

            # delete all assignments not defined by this jwt ...
            for assignment in RoleUserAssignment.objects.filter(user=self.common_auth.user, role_definition=roledef).exclude(object_id__in=team_pks):
                team = Team.objects.get(pk=assignment.object_id)
                roledef.remove_permission(self.common_auth.user, team)

            # assign "non-local" for each team ...
            for team in teams:
                roledef.give_permission(self.common_auth.user, team)

        auditor_roledef = RoleDefinition.objects.get(name='Platform Auditor')
        if "Platform Auditor" in self.common_auth.token.get('global_roles', []):
            auditor_roledef.give_global_permission(self.common_auth.user)
        else:
            auditor_roledef.remove_global_permission(self.common_auth.user)
