# Python
import logging

from ansible_base.jwt_consumer.common.auth import JWTAuthentication

logger = logging.getLogger('ansible_base.jwt_consumer.awx.auth')


class AwxJWTAuthentication(JWTAuthentication):
    # Object-role claims are applied through the shared RBAC bulk pipeline
    # (save_user_claims -> bulk_give_permissions / remove_assignments). The old AWX
    # Role.members mirror is kept in sync by AWX's own handlers on the
    # dab_rbac_assignments_created / dab_rbac_assignments_pre_delete signals, so no
    # JWT-consumer-specific sync is needed here.
    use_rbac_permissions = True
