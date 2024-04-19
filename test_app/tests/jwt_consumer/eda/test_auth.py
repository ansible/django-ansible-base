import logging
import sys
from unittest.mock import MagicMock

from ansible_base.jwt_consumer.eda.auth import EDAJWTAuthentication


def test_eda_process_permissions(user, caplog):
    authentication = EDAJWTAuthentication()
    claims = {}
    token = {}
    with caplog.at_level(logging.INFO):
        authentication.process_permissions(user, claims, token)
        assert f"Processing permissions for {user.username}" in caplog.text


def test_eda_jwt_auth_scheme():
    sys.modules['aap_eda.core'] = MagicMock()
    from ansible_base.jwt_consumer.eda.auth import EDAJWTAuthScheme  # noqa: E402

    scheme = EDAJWTAuthScheme(None)
    response = scheme.get_security_definition(None)
    assert 'name' in response and response['name'] == 'X-DAB-JW-TOKEN'
