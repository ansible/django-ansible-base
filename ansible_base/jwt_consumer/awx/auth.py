# Python
import logging

from ansible_base.jwt_consumer.common.auth import JWTAuthentication

logger = logging.getLogger('ansible_base.jwt_consumer.awx.auth')


class AwxJWTAuthentication(JWTAuthentication):
    use_rbac_permissions = True
