# Python
import logging

from ansible_base.lib.jwt_auth.common.auth import JWTAuthentication

logger = logging.getLogger('ansible_base.lib.jwt_auth.awx.auth')


class AwxJWTAuthentication(JWTAuthentication):
    def process_permissions(self, user, claims, token):
        logger.error("Processing claims for {}".format(user.username))
