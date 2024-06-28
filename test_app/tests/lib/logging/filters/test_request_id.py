import io
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


@pytest.mark.parametrize(
    "request_id, valid",
    [
        ("6621b67a-9088-4513-8f58-35989472c6d0", True),
        ("invalid", False),
        ("", False),
        (None, False),
    ],
)
def test_request_id_flow(request_id, valid, admin_api_client):
    """
    Test the whole flow, through the middleware, and ensure the request id shows
    up when expected, in the logging output.

    This is derived from https://stackoverflow.com/a/61614082
    """

    stream = io.StringIO()
    root_logger = logging.getLogger()
    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter('(test_request_id_flow) %(asctime)s %(levelname)-8s [%(request_id)s]  %(name)s %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    if request_id is not None:
        admin_api_client.get("/", HTTP_X_REQUEST_ID=request_id)
    else:
        admin_api_client.get("/")

    handler.flush()
    handler.close()

    log_output = stream.getvalue()

    # Sanity, ensure we are using the correct formatter
    assert "(test_request_id_flow)" in log_output

    # Ensure the request id is in the log output, if it was valid
    if valid:
        assert f"[{request_id}] " in log_output
    else:
        assert "[] " in log_output
