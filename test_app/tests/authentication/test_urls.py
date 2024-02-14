import importlib

import pytest
from django.test.utils import override_settings


@pytest.mark.parametrize(
    'setting',
    (
        (None),
        ('junk'),
        ('ansible_base.authentication.views'),
        ('ansible_base.authentication.views.AuthenticatorViewSet'),
    ),
)
def test_authentication_urls_setting(setting):
    from ansible_base.authentication import urls

    with override_settings(ANSIBLE_BASE_USER_VIEWSET=setting):
        importlib.reload(urls)
