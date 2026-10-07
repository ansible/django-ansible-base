from ansible_base.jwt_consumer.awx.auth import AwxJWTAuthentication


def test_awx_process_permissions(user, caplog):
    authentication = AwxJWTAuthentication()
    assert authentication.use_rbac_permissions is True
