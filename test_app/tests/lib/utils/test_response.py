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
    "front_end_url",
    [
        ("https://www.example.com/something"),
        (None),
    ],
)
def test_get_fully_qualified_url(front_end_url):
    scheme = 'https'
    host = 'localhost'
    port = 1234

    request = RequestFactory().get('/fake_path', **{'SERVER_PORT': port, 'wsgi.url_scheme': scheme, 'SERVER_NAME': host})
    with override_settings(FRONT_END_URL=front_end_url):
        url = get_fully_qualified_url('user-list', request=request)
        if front_end_url:
            assert url.startswith(front_end_url), f"expected {url} to start with {front_end_url}"
            assert url != front_end_url, f"{url} should have more than just {front_end_url}"
        else:
            url_constructed_from_request = f"{scheme}://{host}:{port}"
            assert url.startswith(url_constructed_from_request), f"expected {url} to start with {url_constructed_from_request}"
            assert url != url_constructed_from_request, f"{url} should have more than just {url_constructed_from_request}"
