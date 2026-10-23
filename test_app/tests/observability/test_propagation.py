from unittest.mock import MagicMock

import requests
from requests.structures import CaseInsensitiveDict

from ansible_base.observability.propagation import (
    _active_propagation_headers,
    headers_to_propagate,
    outgoing_request_hook,
    request_hook,
    response_hook,
)


def test_x_test_name_header_propagation(settings, rf):
    settings.ANSIBLE_OBSERVABILITY_CAPTURE_HEADERS = ['x-test-name']

    request = rf.get('/', HTTP_X_TEST_NAME='myvalue')
    request_hook(MagicMock(), request)

    try:
        active = _active_propagation_headers.get()
        assert active.get('X-TEST-NAME') == 'myvalue'
    finally:
        response_hook(MagicMock(), request, MagicMock())


def test_regex_pattern_matches_header(settings):
    settings.ANSIBLE_OBSERVABILITY_CAPTURE_HEADERS = ['x-correlation-.*']

    meta = {'HTTP_X_CORRELATION_FOO': 'bar'}
    result = headers_to_propagate(meta)

    assert result == {'X-CORRELATION-FOO': 'bar'}


def test_no_patterns_returns_empty(settings):
    settings.ANSIBLE_OBSERVABILITY_CAPTURE_HEADERS = []

    meta = {'HTTP_ACCEPT_LANGUAGE': 'en-US', 'HTTP_X_CORRELATION_ID': 'abc'}
    result = headers_to_propagate(meta)

    assert result == {}


def test_outgoing_request_hook_injects_headers():
    token = _active_propagation_headers.set({'X-My-Header': 'injected-value'})
    try:
        req = requests.PreparedRequest()
        req.headers = CaseInsensitiveDict()

        outgoing_request_hook(MagicMock(), req)

        assert req.headers.get('X-My-Header') == 'injected-value'
    finally:
        _active_propagation_headers.reset(token)


def test_response_hook_resets_contextvar(settings, rf):
    settings.ANSIBLE_OBSERVABILITY_CAPTURE_HEADERS = ['x-test-name']

    request = rf.get('/', HTTP_X_TEST_NAME='resetme')
    request_hook(MagicMock(), request)

    assert _active_propagation_headers.get().get('X-TEST-NAME') == 'resetme'

    response_hook(MagicMock(), request, MagicMock())

    assert _active_propagation_headers.get() == {}
