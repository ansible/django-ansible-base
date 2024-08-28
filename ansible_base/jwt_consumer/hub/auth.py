import logging

from django.contrib.contenttypes.models import ContentType

from ansible_base.jwt_consumer.common.auth import JWTAuthentication
from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.resource_registry.models import Resource
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment


logger = logging.getLogger('ansible_base.jwt_consumer.hub.auth')


class HubJWTAuth(JWTAuthentication):

    def get_galaxy_models_and_functions(self):
        '''This is separate from process_permissions purely for testability.'''
        try:
            from galaxy_ng.app.models import Organization, Team
            from pulpcore.plugin.util import assign_role, remove_role
        except ImportError:
            raise InvalidService("automation-hub")

        return Organization, Team, assign_role, remove_role

    def process_permissions(self):
        # Map teams in the JWT to Automation Hub groups.
        Organization, Team, assign_role, remove_role = self.get_galaxy_models_and_functions()
        self.team_content_type = ContentType.objects.get_for_model(Team)
        self.org_content_type = ContentType.objects.get_for_model(Organization)

        admin_orgs = []
        member_orgs = []
        admin_teams = []
        member_teams = []
        groups = []
        for role_name in self.common_auth.token.get('object_roles', {}).keys():
            if role_name.startswith('Org'):
                for object_index in self.common_auth.token['object_roles'][role_name]['objects']:
                    org_data = self.common_auth.token['objects']['organization'][object_index]
                    ansible_id = org_data['ansible_id']

                    try:
                        org = Resource.objects.get(ansible_id=ansible_id).content_object
                    except Resource.DoesNotExist:
                        org = self.common_auth.get_or_create_resource('organization', org_data)[1]

                    if role_name == 'Organization Admin':
                        admin_orgs.append(org)
                    else:
                        member_orgs.append(org)

            if role_name.startswith('Team'):
                for object_index in self.common_auth.token['object_roles'][role_name]['objects']:
                    team_data = self.common_auth.token['objects']['team'][object_index]
                    ansible_id = team_data['ansible_id']
                    try:
                        team = Resource.objects.get(ansible_id=ansible_id).content_object
                    except Resource.DoesNotExist:
                        team = self.common_auth.get_or_create_resource('team', team_data)[1]

                    groups.append(team.group)

                    if role_name == 'Team Member':
                        member_teams.append(team)

        self.common_auth.user.groups.set(groups)

        '''
        # manage org membership ...
        org_pks = [org.pk for org in orgs]
        for org in Organization.objects.exclude(pk__in=org_pks).filter(users=self.common_auth.user):
            org.users.remove(self.common_auth.user)
        for org in orgs:
            org.users.add(self.common_auth.user)
        '''

        # pks for filtering ...
        member_team_pks = [team.pk for team in member_teams]

        # the "shared" "non-local" role definition ...
        team_roledef = RoleDefinition.objects.get(name='Team Member')

        # delete all memberships not defined by this jwt ...
        for assignment in RoleUserAssignment.objects.filter(
            user=self.common_auth.user, role_definition=team_roledef
        ).exclude(object_id__in=member_team_pks):
            # assignment.delete()
            team_roledef.remove_permission(self.common_auth.user, assignment.team)

        # assign "non-local" membership for each team ...
        for team in member_teams:
            team_roledef.give_permission(self.common_auth.user, team)

        auditor_roledef = RoleDefinition.objects.get(name='Platform Auditor')
        if "Platform Auditor" in self.common_auth.token.get('global_roles', []):
            auditor_roledef.give_global_permission(self.common_auth.user)
        else:
            auditor_roledef.remove_global_permission(self.common_auth.user)
