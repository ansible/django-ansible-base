import sys
from unittest.mock import MagicMock

from ansible_base.jwt_consumer.eda.auth import EDAJWTAuthentication


def test_eda_process_permissions(user, caplog):
    authentication = EDAJWTAuthentication()
    assert authentication.use_rbac_permissions is True


def test_eda_jwt_auth_scheme():
    sys.modules['aap_eda.core'] = MagicMock()
    from ansible_base.jwt_consumer.eda.auth import EDAJWTAuthScheme  # noqa: E402

    scheme = EDAJWTAuthScheme(None)
    response = scheme.get_security_definition(None)
    assert 'name' in response and response['name'] == 'X-DAB-JW-TOKEN'
