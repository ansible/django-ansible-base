import pytest
from unittest.mock import Mock

from ansible_base.lib.utils.context_processors import version


class TestContextProcessors:
    def test_version_with_no_view(self):
        """Test context processor when no view is in parser_context."""
        request = Mock()
        request.parser_context = {}

        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''
        assert 'api_version' in result

    def test_version_with_deprecated_view_dict(self):
        """Test context processor with new deprecation dict."""
        view = Mock()
        view.deprecation = {
            'detail': 'This endpoint is deprecated.',
            'link': 'https://example.com/docs'
        }
        view.deprecated = False

        request = Mock()
        request.parser_context = {'view': view}

        result = version(request)

        assert result['deprecated'] is True
        assert result['deprecated_message'] == 'This endpoint is deprecated.'
        assert result['deprecated_link'] == 'https://example.com/docs'

    def test_version_with_deprecated_view_dict_no_link(self):
        """Test context processor with deprecation dict but no link."""
        view = Mock()
        view.deprecation = {
            'detail': 'This endpoint is deprecated.',
            'link': None
        }
        view.deprecated = False

        request = Mock()
        request.parser_context = {'view': view}

        result = version(request)

        assert result['deprecated'] is True
        assert result['deprecated_message'] == 'This endpoint is deprecated.'
        assert 'deprecated_link' not in result

    def test_version_with_legacy_deprecated_boolean(self):
        """Test context processor with legacy deprecated boolean."""
        view = Mock()
        view.deprecation = None
        view.deprecated = True

        request = Mock()
        request.parser_context = {'view': view}

        result = version(request)

        assert result['deprecated'] is True
        assert 'deprecated' in result['deprecated_message'].lower()

    def test_version_with_non_deprecated_view(self):
        """Test context processor with non-deprecated view."""
        view = Mock()
        view.deprecation = None
        view.deprecated = False

        request = Mock()
        request.parser_context = {'view': view}

        result = version(request)

        assert result['deprecated'] is False
        assert result['deprecated_message'] == ''


@pytest.mark.django_db
class TestContextProcessorIntegration:
    """Integration tests with actual DRF views."""

    def test_deprecated_endpoint_context(self, admin_api_client):
        """Test context processor detects deprecated endpoint."""
        from test_app.views import DeprecatedEndpointViewSet
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/api/v1/deprecated_endpoint/')

        # Create a mock DRF request with parser_context
        view = DeprecatedEndpointViewSet()
        mock_request = Mock()
        mock_request.parser_context = {'view': view}

        result = version(mock_request)

        assert result['deprecated'] is True
        assert 'deprecated' in result['deprecated_message'].lower()

    def test_legacy_deprecated_endpoint_context(self):
        """Test context processor detects legacy deprecated endpoint."""
        from test_app.views import LegacyDeprecatedViewSet
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/api/v1/legacy_deprecated/')

        # Create a mock DRF request with parser_context
        view = LegacyDeprecatedViewSet()
        mock_request = Mock()
        mock_request.parser_context = {'view': view}

        result = version(mock_request)

        assert result['deprecated'] is True
        assert 'deprecated' in result['deprecated_message'].lower()
