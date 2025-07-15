import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.query import IntegrityError

from ansible_base.jwt_consumer.common.auth import JWTAuthentication
from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from ansible_base.resource_registry.models import Resource

logger = logging.getLogger('ansible_base.jwt_consumer.hub.auth')


class HubJWTAuth(JWTAuthentication):
    """
    Automation Hub-specific JWT authentication and permission processing.

    Extends JWTAuthentication to map JWT team and auditor roles to Automation Hub groups and permissions.

    Methods:
        - get_galaxy_models: Import and return Organization and Team models from Galaxy/Automation Hub.
        - process_permissions: Main entry for mapping JWT claims to Hub permissions.
        - _collect_team_roles: Collects admin/member teams from JWT claims.
        - _process_team_role: Processes a single team role from JWT claims.
        - _get_or_create_team: Gets or creates a team resource from JWT data.
        - _sync_team_assignments: Syncs team assignments for admin/member roles.
        - _remove_unmatched_assignments: Removes assignments not present in JWT.
        - _sync_auditor_role: Syncs Platform Auditor global role.
    """

    def get_galaxy_models(self):
        '''This is separate from process_permissions purely for testability.'''
        try:
            from galaxy_ng.app.models import Organization, Team
        except ImportError:
            raise InvalidService("automation-hub")

        return Organization, Team

    def process_permissions(self):
        # Map teams in the JWT to Automation Hub groups.
        organization, team = self.get_galaxy_models()
        self.team_content_type = ContentType.objects.get_for_model(team)
        self.org_content_type = ContentType.objects.get_for_model(organization)

        admin_teams, member_teams = self._collect_team_roles()

        self._sync_team_assignments(team, admin_teams, member_teams)
        self._sync_auditor_role()

    def _collect_team_roles(self):
        admin_teams = []
        member_teams = []
        object_roles = self.common_auth.token.get('object_roles', {})
        for role_name in object_roles.keys():
            if role_name.startswith('Team'):
                self._process_team_role(role_name, admin_teams, member_teams)
        return admin_teams, member_teams

    def _process_team_role(self, role_name, admin_teams, member_teams):
        for object_index in self.common_auth.token['object_roles'][role_name]['objects']:
            team_data = self.common_auth.token['objects']['team'][object_index]
            team = self._get_or_create_team(team_data)
            if not team:
                continue
            if role_name == 'Team Admin':
                admin_teams.append(team)
            elif role_name == 'Team Member':
                member_teams.append(team)

    def _get_or_create_team(self, team_data):
        ansible_id = team_data['ansible_id']
        try:
            return Resource.objects.get(ansible_id=ansible_id).content_object
        except Resource.DoesNotExist:
            try:
                return self.common_auth.get_or_create_resource('team', team_data)[1]
            except IntegrityError as e:
                logger.warning(
                    f"Got integrity error ({e}) on {team_data}. Skipping team assignment. "
                    "Please make sure the sync task is running to prevent this warning in the future."
                )
                return None

    def _sync_team_assignments(self, team, admin_teams, member_teams):
        for roledef_name, teams in [('Team Admin', admin_teams), ('Team Member', member_teams)]:
            roledef = RoleDefinition.objects.get(name=roledef_name)
            team_pks = [team.pk for team in teams]
            self._remove_unmatched_assignments(team, roledef, team_pks)
            for team in teams:
                roledef.give_permission(self.common_auth.user, team)

    def _remove_unmatched_assignments(self, team, roledef, team_pks):
        assignments = RoleUserAssignment.objects.filter(user=self.common_auth.user, role_definition=roledef).exclude(object_id__in=team_pks)
        for assignment in assignments:
            team = team.objects.get(pk=assignment.object_id)
            roledef.remove_permission(self.common_auth.user, team)

    def _sync_auditor_role(self):
        auditor_roledef = RoleDefinition.objects.get(name='Platform Auditor')
        if "Platform Auditor" in self.common_auth.token.get('global_roles', []):
            auditor_roledef.give_global_permission(self.common_auth.user)
        else:
            auditor_roledef.remove_global_permission(self.common_auth.user)
