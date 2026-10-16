import pytest
from unittest.mock import Mock, patch

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
        assert result['deprecated_message'] == ('This resource has been deprecated and will be removed in a future release.')

    def test_version_with_non_deprecated_view(self):
        view = Mock()
        view.deprecation = None
        view.deprecated = False
        request = Mock()
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''

    def test_version_with_missing_parser_context(self):
        request = Mock(spec=[])
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''
        assert result['api_version'] == 'Unknown'

    def test_version_with_deprecation_dict_missing_detail_key(self):
        view = Mock()
        view.deprecation = {'reason': 'deprecated'}
        view.deprecated = False
        request = Mock()
        request.parser_context = {'view': view}

        with pytest.raises(KeyError):
            version(request)

    @patch('ansible_base.lib.utils.context_processors.get_function_from_setting')
    def test_version_with_version_function_exception(self, mock_get_function):
        mock_get_function.side_effect = Exception('Version function error')
        request = Mock()
        request.parser_context = {}
        result = version(request)

        assert result['api_version'] == 'Unknown'
        assert result['deprecated'] is False

    @patch('ansible_base.lib.utils.context_processors.get_function_from_setting')
    def test_version_with_version_function_success(self, mock_get_function):
        mock_version_func = Mock(return_value='2.5.1')
        mock_get_function.return_value = mock_version_func
        request = Mock()
        request.parser_context = {}
        result = version(request)

        assert result['api_version'] == '2.5.1'
