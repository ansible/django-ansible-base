import csv
from io import StringIO

import pytest
from django.test import override_settings
from django.test.client import RequestFactory

from ansible_base.lib.utils.response import CSVStreamResponse, get_fully_qualified_url, get_relative_url


def test_csv_stream_response():
    expected = [b'header,other\r\n', b'data0,other0\r\n', b'data1,other1\r\n', b'data2,other2\r\n', b'data3,other3\r\n', b'data4,other4\r\n']

    def data_generator():
        yield ["header", "other"]
        for i in range(5):
            yield [f"data{i}", f"other{i}"]

    stream = CSVStreamResponse(data_generator(), filename="manifest.csv").stream()
    response = list(stream.streaming_content)
    assert response == expected

    csv_file = StringIO("".join(item.decode() for item in response))
    for ix, row in enumerate(csv.DictReader(csv_file)):
        assert row == {"header": f"data{ix}", "other": f"other{ix}"}


def test_get_relative_url():
    # This should only return a relative URL (no server:port, etc)
    url = get_relative_url('user-list')
    assert url.startswith('/')


@pytest.mark.parametrize(
    "front_end_url, with_request, expected",
    [
        pytest.param(
            "https://frontend.example.com/something", True, "https://frontend.example.com/something/api/v1/users/", id="front_end_url overrides request host"
        ),
        pytest.param(
            "https://frontend.example.com/something",
            False,
            "https://frontend.example.com/something/api/v1/users/",
            id="front_end_url is used if request is absent",
        ),
        pytest.param(None, True, "https://dab.example.com:1234/api/v1/users/", id="front_end_url undefined but can get host from request"),
        pytest.param(None, False, "/api/v1/users/", id="front_end_url undefined and no request, fall back to relative"),
    ],
)
def test_get_fully_qualified_url(front_end_url, with_request, expected):
    scheme = 'https'
    host = 'dab.example.com'
    port = 1234

    if with_request:
        request = RequestFactory().get('/fake_path', **{'SERVER_PORT': port, 'wsgi.url_scheme': scheme, 'SERVER_NAME': host})
    else:
        request = None

    with override_settings(FRONT_END_URL=front_end_url):
        url = get_fully_qualified_url('user-list', request=request)
        assert url == expected
