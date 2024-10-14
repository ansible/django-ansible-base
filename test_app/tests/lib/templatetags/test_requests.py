import crum
import pytest
from django.test.client import RequestFactory

from ansible_base.jwt_consumer.common.util import generate_x_trusted_proxy_header
from ansible_base.lib.templatetags.requests import is_proxied_request


@pytest.mark.parametrize(
    "httprequest,headers,expected_result",
    [
        (False, {}, False),
        (True, {}, False),
        (True, {'X_TRUSTED_PROXY': 'something'}, False),
        (True, 'mismatch', False),
        (True, 'rsa_keypair', True),
    ],
)
def test_is_proxied_request(request, httprequest, headers, expected_result, settings):
    """
    This just returns ansible_base.lib.utils.requests.is_proxied_request()
    """
    if headers == 'mismatch':
        random_key = request.getfixturevalue('random_public_key')
        rsa_keypair = request.getfixturevalue('rsa_keypair')
        settings.ANSIBLE_BASE_JWT_KEY = random_key
        headers = {'X_TRUSTED_PROXY': generate_x_trusted_proxy_header(rsa_keypair.private)}
    elif headers == 'rsa_keypair':
        key = request.getfixturevalue('rsa_keypair')
        settings.ANSIBLE_BASE_JWT_KEY = key.public
        headers = {'X_TRUSTED_PROXY': generate_x_trusted_proxy_header(key.private)}

    if httprequest:
        rf_request = RequestFactory().get('/hello', headers=headers)
    else:
        rf_request = None

    try:
        crum.set_current_request(rf_request)
        assert is_proxied_request() == expected_result
    finally:
        crum.set_current_request(None)
