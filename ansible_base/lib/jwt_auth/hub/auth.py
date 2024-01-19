from ansible_base.lib.jwt_auth.common.auth import JWTAuthentication
from ansible_base.lib.jwt_auth.common.exceptions import InvalidService


class HubJWTAuth(JWTAuthentication):
    def process_permissions(self, user, claims, token):
        # Map teams in the JWT to Automation Hub groups.
        try:
            from galaxy_ng.app.models.auth import Group
        except ImportError:
            raise InvalidService("automation-hub")

        for team in claims.get("teams", []):
            hub_group, _ = Group.objects.get_or_create(name=team["name"])
            hub_group.user_set.add(user)
