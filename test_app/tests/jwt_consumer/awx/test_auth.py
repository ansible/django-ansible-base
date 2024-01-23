import logging

from ansible_base.jwt_consumer.awx.auth import AwxJWTAuthentication


def test_awx_process_permissions(user, caplog):
    authentication = AwxJWTAuthentication()
    claims = {}
    token = {}
    with caplog.at_level(logging.ERROR):
        authentication.process_permissions(user, claims, token)
        assert f"Processing claims for {user.username}" in caplog.text
