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

            self.team_content_type = ContentType.objects.get_for_model(Team)
            self.org_content_type = ContentType.objects.get_for_model(Organization)
        except ImportError:
            raise InvalidService("automation-hub")

        for role_name in self.common_auth.token.get('object_roles', {}).keys():
            if role_name.startswith('Team'):
                for object_index in self.common_auth.token['object_roles'][role_name]['objects']:
                    team_data = self.common_auth.token['objects']['team'][object_index]
                    ansible_id = team_data['ansible_id']
                    try:
                        resource = Resource.objects.get(ansible_id=ansible_id)
                    except Resource.DoesNotExist:
                        try:
                            resource = self.get_or_create_resource('team', team_data)
                        except Exception as e:
                            logger.error(f"Failed to request object {ansible_id} from gateway to grant permissions to {self.common_auth.user.username}: {e}")

                    # Because RoleDefinition, Team and Group are all linked we don't have to go through individual lookups nor do we need to catch DoesNotExist
                    team = Team.objects.get(id=resource.object_id)
                    team.group.user_set.add(self.common_auth.user)

        if "Platform Auditor" in self.common_auth.token.get('global_roles', []):
            # Add platform operator here
            pass
