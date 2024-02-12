import logging

from ansible_base.jwt_consumer.common.auth import JWTAuthentication
from ansible_base.jwt_consumer.common.exceptions import InvalidService

try:
    from aap_eda.core import models
    from drf_spectacular.extensions import OpenApiAuthenticationExtension
except ImportError:
    raise InvalidService("eda")

logger = logging.getLogger("ansible_base.jwt_consumer.eda.auth")


class EDAJWTAuthentication(JWTAuthentication):
    def process_permissions(self, user, claims, token):
        logger.info("Processing permissions")

        if token.get("is_superuser", False):
            self._add_roles(user, "Admin", "is_superuser")

        if token.get("is_system_auditor", False):
            self._add_roles(user, "Auditor", "is_system_auditor")

    def _add_roles(self, user, role_name, user_type):
        logger.info(f"{user.username} is {user_type}. Adding role {role_name} to user {user.username}")
        role_id = models.Role.objects.filter(name=role_name).first().id
        user.roles.add(role_id)


class EDAJWTAuthScheme(OpenApiAuthenticationExtension):
    target_class = EDAJWTAuthentication
    name = "EDAJWTAuthentication"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "name": "X-DAB-JW-TOKEN", "in": "header"}
