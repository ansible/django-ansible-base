import pytest
from django.http.response import HttpResponseBase
from django.test import override_settings
from django.test.client import RequestFactory

from ansible_base.lib.utils.views import AnsibleBaseView


@pytest.fixture
def view_with_headers():
    view = AnsibleBaseView()
    view.headers = {}
    return view


@pytest.fixture
def mock_request():
    rf = RequestFactory()
    get_request = rf.get('/hello/')
    return get_request


@pytest.fixture
def default_headers():
    return {'Content-Type': 'text/html; charset=utf-8'}


def test_header_view_with_no_headers(view_with_headers, mock_request, default_headers):
    initial_response = HttpResponseBase()
    response = view_with_headers.finalize_response(mock_request, initial_response)
    assert response.headers == default_headers


@pytest.mark.parametrize(
    "headers, expected_headers",
    [
        # Setting expected_headers to none will assume what goes in should come out
        ({}, None),
        ({"TEST": 'testing'}, None),
        ({'TEST1': 'testing1', 'TEST2': 'testing2'}, None),
        ({1: 'testing1'}, {}),
        ({"TEST": 1}, {}),
        ({1: 'testing1', 'TEST2': 'testing2'}, {'TEST2': 'testing2'}),
        ({"TEST": 1, False: True, 'a_dict': {}, 'a_set': (), 'an_array': []}, {}),
    ],
)
def test_header_view_with_headers(view_with_headers, mock_request, default_headers, headers, expected_headers):
    with override_settings(ANSIBLE_BASE_EXTRA_HEADERS=headers):
        initial_response = HttpResponseBase()
        response = view_with_headers.finalize_response(mock_request, initial_response)
        if expected_headers is None:
            default_headers.update(headers)
        else:
            default_headers.update(expected_headers)
        assert response.headers == default_headers
