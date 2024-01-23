# Python
import logging

from ansible_base.jwt_consumer.common.auth import JWTAuthentication

logger = logging.getLogger('ansible_base.jwt_consumer.awx.auth')


class AwxJWTAuthentication(JWTAuthentication):
    def process_permissions(self, user, claims, token):
        logger.error("Processing claims for {}".format(user.username))
