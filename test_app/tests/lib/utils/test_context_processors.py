import pytest
from unittest.mock import Mock

from ansible_base.lib.utils.context_processors import version


class TestContextProcessors:
    def test_version_with_no_view(self):
        request = Mock()
        request.parser_context = {}
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''
        assert 'api_version' in result

    def test_version_with_deprecated_view_dict(self):
        view = Mock()
        view.deprecation = {
            'detail': 'This endpoint is deprecated.',
        }
        view.deprecated = False
        request = Mock()
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is True
        assert result['deprecated_message'] == 'This endpoint is deprecated.'

    def test_version_with_legacy_deprecated_boolean(self):
        view = Mock()
        view.deprecation = None
        view.deprecated = True
        request = Mock()
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is True
        assert 'deprecated' in result['deprecated_message'].lower()

    def test_version_with_non_deprecated_view(self):
        view = Mock()
        view.deprecation = None
        view.deprecated = False
        request = Mock()
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''


