import logging

from ansible_base.jwt_consumer.common.auth import JWTAuthentication

logger = logging.getLogger('ansible_base.jwt_consumer.hub.auth')


class HubJWTAuth(JWTAuthentication):
    use_rbac_permissions = True
