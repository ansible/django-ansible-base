import logging
import sys
from unittest.mock import MagicMock

import pytest


def test_eda_import_error():
    from ansible_base.lib.jwt_auth.common.exceptions import InvalidService

    with pytest.raises(InvalidService):
        import ansible_base.lib.jwt_auth.eda.auth  # noqa: 401


def test_eda_jwt_auth_scheme():
    sys.modules['aap_eda.core'] = MagicMock()
    from ansible_base.lib.jwt_auth.eda.auth import EDAJWTAuthScheme  # noqa: E402

    scheme = EDAJWTAuthScheme(None)
    response = scheme.get_security_definition(None)
    assert 'name' in response and response['name'] == 'JWT Authorization'


def filter_function(name):
    role = None
    if name == 'Admin':
        role = MagicMock(id=1)
    elif name == 'Auditor':
        role = MagicMock(id=2)
    return MagicMock(**{'first.return_value': role})


@pytest.fixture
def mocked_authenticator():
    sys.modules['aap_eda.core'] = MagicMock()
    from ansible_base.lib.jwt_auth.eda.auth import EDAJWTAuthentication  # noqa: E402
    from ansible_base.lib.jwt_auth.eda.auth import models

    models.Role.objects.filter = filter_function

    authenticator = EDAJWTAuthentication()
    # patch.object(authenticator.models.Role.objects, 'filter', alan_filter)
    # authenticator.models = MagicMock(**{"Role.objects.filter": filter_function})
    return authenticator


def test_eda_jwt_auth_add_roles(mocked_authenticator, caplog):
    with caplog.at_level(logging.INFO):
        user = MagicMock(username='timmy', roles=set())
        user_type = 'super_user'
        role_name = 'Auditor'
        mocked_authenticator._add_roles(user, role_name, user_type)
        assert f"{user.username} is {user_type}. Adding role {role_name} to user {user.username}" in caplog.text


@pytest.mark.parametrize(
    'is_superuser,is_system_auditor,results', ((False, False, set()), (True, False, set([1])), (False, True, set([2])), (True, True, set([1, 2])))
)
def test_eda_jwt_auth_process_permissions(mocked_authenticator, is_superuser, is_system_auditor, results):
    user = MagicMock(username='timmy', roles=set())
    token = {
        'is_superuser': is_superuser,
        'is_system_auditor': is_system_auditor,
    }
    mocked_authenticator.process_permissions(user, {}, token)
    assert user.roles == results
