from unittest import mock

import pytest
from django.test import override_settings
from django.test.client import RequestFactory

from ansible_base.jwt_consumer.common.util import generate_x_trusted_proxy_header
from ansible_base.lib.utils.requests import get_remote_host, get_remote_hosts


@pytest.mark.parametrize("return_value,expected_value", [(None, None), ([], None), (['a'], 'a'), (['True', 'False'], 'True')])
def test_get_remote_host(return_value, expected_value):
    """
    Test that get_remote_host always returns None or the first value given back from get_remote_hosts
    """
    generic_request = RequestFactory().get('/hello')
    with mock.patch('ansible_base.lib.utils.requests.get_remote_hosts', return_value=return_value):
        assert get_remote_host(generic_request) == expected_value


def test_get_remote_hosts_no_headers():
    generic_request = RequestFactory().get('/hello')
    del generic_request.META
    assert get_remote_hosts(generic_request) == []


@pytest.mark.parametrize(
    "headers,extra,get_first_only,expected_result",
    [
        # Default test remote addr
        ({}, {}, False, ['127.0.0.1']),
        ({}, {}, True, ['127.0.0.1']),
        # Override remote addr
        ({}, {'REMOTE_ADDR': '1.2.3.4'}, True, ['1.2.3.4']),
        # Multiple addresses
        ({}, {'REMOTE_ADDR': '1.2.3.4, 5.6.7.8'}, True, ['1.2.3.4']),
        ({}, {'REMOTE_ADDR': '1.2.3.4, 5.6.7.8'}, False, ['1.2.3.4', '5.6.7.8']),
        # Validate that variables have no affect if HTTP_X_TRUSTED_HOST is missing
        ({'X_FORWARDED_FOR': '1.2.3.4'}, {}, True, ['127.0.0.1']),
        ({'X_ENVOY_EXTERNAL_ADDRESS': '1.2.3.4'}, {}, True, ['127.0.0.1']),
        # Validate that given the value the trusted header the headers supersede the REMOTE_ADD
        ({'X_TRUSTED_PROXY': '', 'X_FORWARDED_FOR': '1.2.3.4'}, {}, True, ['1.2.3.4']),
        ({'X_TRUSTED_PROXY': '', 'X_ENVOY_EXTERNAL_ADDRESS': '1.2.3.4'}, {}, True, ['1.2.3.4']),
        ({'X_TRUSTED_PROXY': '', 'X_FORWARDED_FOR': '1.2.3.4'}, {}, False, ['1.2.3.4', '127.0.0.1']),
        ({'X_TRUSTED_PROXY': '', 'X_ENVOY_EXTERNAL_ADDRESS': '1.2.3.4'}, {}, False, ['1.2.3.4', '127.0.0.1']),
        # Assert the anticipated load order whit multiple headers
        (
            {
                'X_TRUSTED_PROXY': '',
                'X_FORWARDED_FOR': '1.2.3.4, 5.6.7.8',
                'X_ENVOY_EXTERNAL_ADDRESS': '5.6.7.8, 9.10.11.12',
            },
            {'REMOTE_ADDR': '9.10.11.12', 'REMOTE_HOST': 'localhost, example.com'},
            False,
            ['5.6.7.8', '9.10.11.12', '5.6.7.8', '9.10.11.12', 'localhost', 'example.com'],
        ),
        # Complicated example w/o the trusted_proxy header
        (
            {
                'X_FORWARDED_FOR': '1.2.3.4, 5.6.7.8',
                'X_ENVOY_EXTERNAL_ADDRESS': '5.6.7.8, 9.10.11.12',
            },
            {'REMOTE_ADDR': '9.10.11.12', 'REMOTE_HOST': 'localhost, example.com'},
            False,
            ['9.10.11.12', 'localhost', 'example.com'],
        ),
    ],
)
def test_get_remote_hosts(headers, extra, get_first_only, expected_result, rsa_keypair):
    with override_settings(ANSIBLE_BASE_JWT_KEY=rsa_keypair.public):
        if 'X_TRUSTED_PROXY' in headers:
            headers['X_TRUSTED_PROXY'] = generate_x_trusted_proxy_header(rsa_keypair.private)
        request = RequestFactory().get('/hello', headers=headers, **extra)
        remote_hosts = get_remote_hosts(request, get_first_only=get_first_only)
        assert remote_hosts == expected_result


def test_get_remote_hosts_alternate_headers():
    """
    Alter the REMOTE_HOST_HEADERS setting. This will cause the logic to only look at the headers specified in that array
    So even though REMOTE_ADDR will be present its not specified in the list of headers so it won't be included in the results
    """
    request = RequestFactory().get('/hello', headers={'X_JOHNS_HEADER': 'a.b.c.d'})
    with override_settings(REMOTE_HOST_HEADERS=['HTTP_X_JOHNS_HEADER']):
        remote_hosts = get_remote_hosts(request, get_first_only=False)
        assert remote_hosts == ['a.b.c.d']


def test_get_remote_hosts_alternate_headers_behind_trusted_proxy(rsa_keypair):
    """
    Same as last test but we are behind a trusted proxy so we will add in those headers regardless of the list
    """
    with override_settings(ANSIBLE_BASE_JWT_KEY=rsa_keypair.public):
        headers = {
            'X_JOHNS_HEADER': 'a.b.c.d',
            'X_TRUSTED_PROXY': generate_x_trusted_proxy_header(rsa_keypair.private),
            'X_FORWARDED_FOR': '1.2.3.4, 5.6.7.8',
            'X_ENVOY_EXTERNAL_ADDRESS': '5.6.7.8, 9.10.11.12',
        }
        request = RequestFactory().get('/hello', headers=headers)
        with override_settings(REMOTE_HOST_HEADERS=['HTTP_X_JOHNS_HEADER']):
            remote_hosts = get_remote_hosts(request, get_first_only=False)
            assert remote_hosts == ['5.6.7.8', '9.10.11.12', '5.6.7.8', 'a.b.c.d']


@mock.patch("ansible_base.lib.utils.requests.validate_x_trusted_proxy_header", side_effect=Exception)
def test_get_remote_hosts_validate_trusted_proxy_header_exception(mock_validate: mock.MagicMock, rsa_keypair, caplog):
    with override_settings(ANSIBLE_BASE_JWT_KEY=rsa_keypair.public):
        headers = {
            'X_TRUSTED_PROXY': generate_x_trusted_proxy_header(rsa_keypair.private),
            'X_FORWARDED_FOR': '1.2.3.4, 5.6.7.8',
            'X_ENVOY_EXTERNAL_ADDRESS': '5.6.7.8, 9.10.11.12',
        }
        request = RequestFactory().get('/hello', headers=headers)
        remote_hosts = get_remote_hosts(request, get_first_only=False)
        mock_validate.assert_called_once()
        assert "Failed to validate HTTP_X_TRUSTED_PROXY" in caplog.text
        assert remote_hosts == ['127.0.0.1']


def test_get_remote_hosts_validate_trusted_proxy_header_failure(random_public_key, rsa_keypair, caplog):
    with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
        headers = {
            'X_TRUSTED_PROXY': generate_x_trusted_proxy_header(rsa_keypair.private),
            'X_FORWARDED_FOR': '1.2.3.4, 5.6.7.8',
            'X_ENVOY_EXTERNAL_ADDRESS': '5.6.7.8, 9.10.11.12',
        }
        request = RequestFactory().get('/hello', headers=headers)
        remote_hosts = get_remote_hosts(request, get_first_only=False)

        assert "Unable to use headers from trusted proxy because shared secret was invalid!" in caplog.text
        assert remote_hosts == ['127.0.0.1']
