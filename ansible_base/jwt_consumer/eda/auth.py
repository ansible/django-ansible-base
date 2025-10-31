import logging

from drf_spectacular.extensions import OpenApiAuthenticationExtension

from ansible_base.jwt_consumer.common.auth import JWTAuthentication

logger = logging.getLogger("ansible_base.jwt_consumer.eda.auth")


class EDAJWTAuthentication(JWTAuthentication):
    use_rbac_permissions = True


class EDAJWTAuthScheme(OpenApiAuthenticationExtension):
    target_class = EDAJWTAuthentication
    name = "EDAJWTAuthentication"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "name": "X-DAB-JW-TOKEN", "in": "header"}
