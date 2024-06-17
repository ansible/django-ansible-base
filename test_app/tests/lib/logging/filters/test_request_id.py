import logging

import pytest
from django.http import HttpRequest

from ansible_base.lib.logging import thread_local
from ansible_base.lib.logging.filters.request_id import RequestIdFilter


@pytest.fixture
def thread_local_request():
    request = HttpRequest()
    request.method = "GET"
    request.path = "/test"
    thread_local.request = request
    yield request
    del thread_local.request


def test_request_id_filter_missing_request():
    filter = RequestIdFilter()
    record = logging.LogRecord(
        name='test',
        level=logging.DEBUG,
        pathname='test.py',
        lineno=1,
        msg='test message',
        args=(),
        exc_info=None,
    )
    assert filter.filter(record)
    assert record.request_id == ""


@pytest.mark.parametrize(
    "request_id, expected_request_id",
    [
        ("6621b67a-9088-4513-8f58-35989472c6d0", "6621b67a-9088-4513-8f58-35989472c6d0"),
        ("invalid", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_request_id_filter_missing_request_id(thread_local_request, request_id, expected_request_id):
    filter = RequestIdFilter()
    record = logging.LogRecord(
        name='test',
        level=logging.DEBUG,
        pathname='test.py',
        lineno=1,
        msg='test message',
        args=(),
        exc_info=None,
    )
    if request_id is not None:
        thread_local.request.META = {
            'HTTP_X_REQUEST_ID': request_id,
        }
    assert filter.filter(record)
    assert record.request_id == expected_request_id
