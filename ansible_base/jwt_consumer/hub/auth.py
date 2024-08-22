# Python
from ansible_base.jwt_consumer.common.auth import JWTAuthentication


class HubJWTAuth(JWTAuthentication):
    use_rbac_permissions = True
