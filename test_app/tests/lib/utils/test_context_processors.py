from unittest.mock import Mock, patch

import pytest

from ansible_base.lib.utils.context_processors import version


class TestContextProcessors:
    def test_version_with_no_view(self):
        """A request without a view still receives version context and no deprecation message."""
        request = Mock()
        request.parser_context = {}
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''
        assert 'api_version' in result

    def test_version_with_deprecated_view_dict(self):
        """Explicit view metadata supplies the template's deprecation flag and message."""
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
        """The legacy boolean flag produces the generic deprecation message."""
        view = Mock()
        view.deprecation = None
        view.deprecated = True
        request = Mock()
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is True
        assert result['deprecated_message'] == ('This resource has been deprecated and will be removed in a future release.')

    def test_version_with_non_deprecated_view(self):
        """A current view does not produce deprecation context."""
        view = Mock()
        view.deprecation = None
        view.deprecated = False
        request = Mock()
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''

    def test_version_with_missing_parser_context(self):
        """Requests without DRF parser context receive safe default values."""
        request = Mock(spec=[])
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''
        assert result['api_version'] == 'Unknown'

    def test_version_with_deprecation_dict_missing_detail_key(self):
        """Explicit deprecation metadata without the required detail raises KeyError."""
        view = Mock()
        view.deprecation = {'reason': 'deprecated'}
        view.deprecated = False
        request = Mock()
        request.parser_context = {'view': view}

        with pytest.raises(KeyError):
            version(request)

    @patch('ansible_base.lib.utils.context_processors.get_function_from_setting')
    def test_version_with_version_function_exception(self, mock_get_function):
        """Failure to load the product-version function falls back to Unknown."""
        mock_get_function.side_effect = Exception('Version function error')
        request = Mock()
        request.parser_context = {}
        result = version(request)

        assert result['api_version'] == 'Unknown'
        assert result['deprecated'] is False

    @patch('ansible_base.lib.utils.context_processors.get_function_from_setting')
    def test_version_with_version_function_success(self, mock_get_function):
        """The configured product-version function supplies the template's version value."""
        mock_version_func = Mock(return_value='2.5.1')
        mock_get_function.return_value = mock_version_func
        request = Mock()
        request.parser_context = {}
        result = version(request)

        assert result['api_version'] == '2.5.1'
