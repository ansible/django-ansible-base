import importlib
import logging
from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http.response import HttpResponseBase
from django.test import override_settings
from django.test.client import RequestFactory
from rest_framework.views import APIView

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
    get_request.user = AnonymousUser()
    return get_request


@pytest.fixture
def default_headers():
    return {'Content-Type': 'text/html; charset=utf-8', 'X-API-Product-Name': 'Unnamed', 'X-API-Node': 'Unknown'}


def test_ansible_base_view_with_no_settings(view_with_headers, mock_request, default_headers):
    initial_response = HttpResponseBase()
    response = view_with_headers.finalize_response(mock_request, initial_response)
    assert response.headers == default_headers


class DummyView(APIView):
    pass


@pytest.mark.parametrize(
    "setting,log_message,default_parent",
    [
        ('junk', 'must be in the format', True),
        ('does.not.exist', 'Failed to find parent view class', True),
        ('test_app.tests.lib.utils.test_views.DummyView', '', False),
    ],
)
def test_ansible_base_view_parent_view(caplog, setting, log_message, default_parent):
    with override_settings(ANSIBLE_BASE_CUSTOM_VIEW_PARENT=setting):
        with caplog.at_level(logging.ERROR):
            import ansible_base.lib.utils.views

            importlib.reload(ansible_base.lib.utils.views)
            from ansible_base.lib.utils.views import AnsibleBaseDjanoAppApiView, AnsibleBaseView  # noqa: F401

            if default_parent:
                assert issubclass(AnsibleBaseDjanoAppApiView, AnsibleBaseView)
            else:
                assert issubclass(AnsibleBaseDjanoAppApiView, DummyView)
            assert log_message in caplog.text


def test_ansible_base_view_parent_view_exception(caplog):
    with override_settings(ANSIBLE_BASE_CUSTOM_VIEW_PARENT='does.not.exist'):
        with caplog.at_level(logging.ERROR):
            with mock.patch('importlib.import_module', side_effect=ImportError("Test Exception")):
                import ansible_base.lib.utils.views

                importlib.reload(ansible_base.lib.utils.views)
                from ansible_base.lib.utils.views import AnsibleBaseDjanoAppApiView, AnsibleBaseView  # noqa: F401

                assert issubclass(AnsibleBaseDjanoAppApiView, AnsibleBaseView)
                assert 'Failed to import' in caplog.text


class DeprecatedView(AnsibleBaseView):
    deprecated = True
    headers = {}


def test_ansible_base_view_deprecated_view(view_with_headers, mock_request, default_headers):
    initial_response = HttpResponseBase()
    view = DeprecatedView()
    response = view.finalize_response(mock_request, initial_response)
    assert 'Warning' in response


def test_ansible_base_view_time_header(view_with_headers, mock_request):
    initial_response = HttpResponseBase()
    view_with_headers.initialize_request(mock_request)
    response = view_with_headers.finalize_response(mock_request, initial_response)
    assert 'X-API-Time' in response


def version_function():
    return "1.2.3"


def version_function_issue():
    raise Exception('Dang')


@pytest.mark.parametrize(
    "setting,value,log_message",
    [
        (None, 'Unknown', ''),
        ('test_app.tests.lib.utils.test_views.version_function', version_function(), ''),
        ('junk', 'Unknown', 'Failed to load function from'),
        ('does.not.exist', 'Unknown', 'Failed to load function from'),
        ('test_app.tests.lib.utils.test_views.version_function_issue', 'Unknown', 'was set but calling it as a function'),
    ],
)
def test_ansible_base_view_version(view_with_headers, mock_request, admin_user, setting, value, log_message, caplog):
    mock_request.user = admin_user
    initial_response = HttpResponseBase()
    with override_settings(ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION=setting):
        with caplog.at_level(logging.ERROR):
            response = view_with_headers.finalize_response(mock_request, initial_response)
            assert 'X-API-Product-Version' in response and response['X-API-Product-Version'] == value
            assert log_message in caplog.text
