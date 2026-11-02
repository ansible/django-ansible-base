from unittest.mock import Mock, patch

import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from ansible_base.lib.utils.context_processors import version
from ansible_base.lib.utils.views.deprecation import deprecated


@pytest.fixture
def method_deprecation_view():
    """Provide a view with a deprecated GET handler and a current POST handler."""

    class ExampleView(APIView):
        authentication_classes = []
        permission_classes = []

        @deprecated(detail='Use the replacement GET endpoint.')
        def get(self, request):
            """Return template context for the deprecated handler."""
            return Response(version(request))

        def post(self, request):
            """Return template context for the current handler."""
            return Response(version(request))

    return ExampleView


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
        view = Mock(spec=['deprecation', 'deprecated'])
        view.deprecation = {
            'detail': 'This endpoint is deprecated.',
        }
        view.deprecated = False
        request = Mock(method='GET')
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is True
        assert result['deprecated_message'] == 'This endpoint is deprecated.'

    def test_version_with_legacy_deprecated_boolean(self):
        """The legacy boolean flag produces the generic deprecation message."""
        view = Mock(spec=['deprecation', 'deprecated'])
        view.deprecation = None
        view.deprecated = True
        request = Mock(method='GET')
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is True
        assert result['deprecated_message'] == ('This resource has been deprecated and will be removed in a future release.')

    def test_version_with_non_deprecated_view(self):
        """A current view does not produce deprecation context."""
        view = Mock(spec=['deprecation', 'deprecated'])
        view.deprecation = None
        view.deprecated = False
        request = Mock(method='GET')
        request.parser_context = {'view': view}
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''

    @pytest.mark.parametrize(
        ('method', 'expected_deprecated', 'expected_detail'),
        [('get', True, 'Use the replacement GET endpoint.'), ('head', True, 'Use the replacement GET endpoint.'), ('post', False, '')],
    )
    def test_version_with_method_deprecation(self, method_deprecation_view, method, expected_deprecated, expected_detail):
        """Only the selected deprecated HTTP handler supplies deprecation context."""
        request = getattr(APIRequestFactory(), method)('/')

        response = method_deprecation_view.as_view()(request)

        assert response.status_code == 200
        assert response.data['deprecated'] is expected_deprecated
        assert response.data['deprecated_message'] == expected_detail

    @pytest.mark.parametrize(
        ('action', 'expected_deprecated', 'expected_detail'),
        [('retrieve', True, 'Use the replacement retrieve action.'), ('list', False, '')],
    )
    def test_version_with_action_deprecation(self, action, expected_deprecated, expected_detail):
        """ViewSet context follows the selected action, not just the shared HTTP method."""

        class ExampleViewSet(ViewSet):
            authentication_classes = []
            permission_classes = []

            @deprecated(detail='Use the replacement retrieve action.')
            def retrieve(self, request):
                """Return template context for the deprecated action."""
                return Response(version(request))

            def list(self, request):
                """Return template context for the current action."""
                return Response(version(request))

        response = ExampleViewSet.as_view({'get': action})(APIRequestFactory().get('/'))

        assert response.status_code == 200
        assert response.data['deprecated'] is expected_deprecated
        assert response.data['deprecated_message'] == expected_detail

    @pytest.mark.parametrize(
        ('method', 'expected_detail'),
        [('get', 'Use the replacement GET endpoint.'), ('head', 'Use the replacement GET endpoint.'), ('post', 'The entire view is deprecated.')],
    )
    def test_version_prefers_method_deprecation_over_view_metadata(self, method_deprecation_view, method, expected_detail):
        """Method metadata takes precedence, while undecorated handlers fall back to view metadata."""
        view = deprecated(detail='The entire view is deprecated.')(method_deprecation_view)
        request = getattr(APIRequestFactory(), method)('/')

        response = view.as_view()(request)

        assert response.status_code == 200
        assert response.data['deprecated'] is True
        assert response.data['deprecated_message'] == expected_detail

    def test_version_with_missing_parser_context(self):
        """Requests without DRF parser context receive safe default values."""
        request = Mock(spec=[])
        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''
        assert result['api_version'] == 'Unknown'

    def test_version_with_deprecation_dict_missing_detail_key(self):
        """Explicit deprecation metadata without the required detail raises KeyError."""
        view = Mock(spec=['deprecation', 'deprecated'])
        view.deprecation = {'reason': 'deprecated'}
        view.deprecated = False
        request = Mock(method='GET')
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
