import logging
from unittest.mock import MagicMock, mock_open, patch

from django.test import override_settings

from ansible_base.lib.jwt_auth.common.views import PlatformUIRedirectView


def test_view_no_redirect_uri_setting(mocked_http):
    request = MagicMock()
    view = PlatformUIRedirectView()
    response = view.finalize_response(request, {})
    assert response.status_code == 404


@override_settings(ANSIBLE_BASE_JWT_REDIRECT_URI='https://example.com')
@override_settings(ANSIBLE_BASE_JWT_KEY='https://example2.com')
def test_view_with_redirect_setting_success_1():
    request = MagicMock()
    view = PlatformUIRedirectView()
    response = view.finalize_response(request, {})
    assert response.status_code == 200
    assert 'https://example.com/redirect/?service=unknown' in str(response.content)


@override_settings(ANSIBLE_BASE_JWT_KEY='https://example2.com/something/else')
@override_settings(ANSIBLE_BASE_JWT_REDIRECT_TYPE='gibberish')
def test_view_with_redirect_setting_success_2():
    request = MagicMock()
    view = PlatformUIRedirectView()
    response = view.finalize_response(request, {})
    assert response.status_code == 200
    assert 'https://example2.com/redirect/?service=gibberish' in str(response.content)


@override_settings(ANSIBLE_BASE_JWT_KEY='https://example.com')
def test_view_with_template_failure(caplog):
    request = MagicMock()
    view = PlatformUIRedirectView()
    with caplog.at_level(logging.ERROR):
        with patch("builtins.open", mock_open()) as mock_file:
            mock_file.side_effect = Exception('forcing raise')
            response = view.finalize_response(request, {})
            print(response.content)
            assert 'Failed to load redirect.html' in caplog.text
            assert response.status_code == 404
