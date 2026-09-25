import pytest
from django.http.response import HttpResponseBase
from django.test import override_settings
from django.test.client import RequestFactory
from rest_framework.response import Response
from rest_framework.views import APIView

from ansible_base.lib.utils.views.deprecation import deprecated, mark_deprecated


class TestMarkDeprecated:
    def _make_response(self):
        return HttpResponseBase()

    def test_sets_all_headers(self):
        response = self._make_response()
        mark_deprecated(response, 'This endpoint is deprecated.', link='https://example.com/changelog')

        assert response['X-Deprecated'] == 'true'
        assert response['X-Deprecated-Detail'] == 'This endpoint is deprecated.'
        assert response['Link'] == '<https://example.com/changelog>; rel="deprecation"'

    def test_appends_trailing_period(self):
        response = self._make_response()
        mark_deprecated(response, 'Missing period')

        assert response['X-Deprecated-Detail'] == 'Missing period.'

    def test_multiple_calls_accumulate_details(self):
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'The old_param parameter is deprecated.')

        assert response['X-Deprecated-Detail'] == 'Endpoint is deprecated. The old_param parameter is deprecated.'

    def test_duplicate_details_not_repeated(self):
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'Endpoint is deprecated.')

        assert response['X-Deprecated-Detail'] == 'Endpoint is deprecated.'

    def test_first_link_wins(self):
        response = self._make_response()
        mark_deprecated(response, 'First.', link='https://first.com')
        mark_deprecated(response, 'Second.', link='https://second.com')

        assert response['Link'] == '<https://first.com>; rel="deprecation"'

    def test_no_link_omits_header(self):
        response = self._make_response()
        with override_settings(ANSIBLE_BASE_DEPRECATION_LINK=''):
            mark_deprecated(response, 'No link.')

        assert 'Link' not in response

    @override_settings(ANSIBLE_BASE_DEPRECATION_LINK='https://default.com/deprecations')
    def test_falls_back_to_setting(self):
        response = self._make_response()
        mark_deprecated(response, 'Uses default link.')

        assert response['Link'] == '<https://default.com/deprecations>; rel="deprecation"'

    def test_explicit_link_overrides_setting(self):
        response = self._make_response()
        with override_settings(ANSIBLE_BASE_DEPRECATION_LINK='https://default.com'):
            mark_deprecated(response, 'Override.', link='https://explicit.com')

        assert response['Link'] == '<https://explicit.com>; rel="deprecation"'

    def test_x_deprecated_is_idempotent(self):
        response = self._make_response()
        mark_deprecated(response, 'First.')
        mark_deprecated(response, 'Second.')

        assert response['X-Deprecated'] == 'true'


class TestDeprecatedDecoratorMethod:
    def test_method_decorator_sets_headers(self):
        class MyView(APIView):
            @deprecated(detail='The get method is deprecated.', link='https://example.com')
            def get(self, request):
                return Response({'ok': True})

        view = MyView()
        factory = RequestFactory()
        request = factory.get('/')
        response = view.get(request)

        assert response['X-Deprecated'] == 'true'
        assert response['X-Deprecated-Detail'] == 'The get method is deprecated.'
        assert response['Link'] == '<https://example.com>; rel="deprecation"'

    def test_method_decorator_preserves_function_name(self):
        class MyView(APIView):
            @deprecated(detail='Deprecated.')
            def get(self, request):
                """Original docstring."""
                return Response({})

        assert MyView.get.__name__ == 'get'
        assert MyView.get.__doc__ == 'Original docstring.'

    def test_method_decorator_sets_deprecation_dict(self):
        class MyView(APIView):
            @deprecated(detail='Test detail.', link='https://test.com')
            def get(self, request):
                return Response({})

        assert hasattr(MyView.get, 'deprecation')
        assert MyView.get.deprecation == {'detail': 'Test detail.', 'link': 'https://test.com'}


class TestDeprecatedDecoratorClass:
    def test_class_decorator_sets_deprecation_dict(self):
        @deprecated(detail='This view is deprecated.')
        class MyView(APIView):
            pass

        assert hasattr(MyView, 'deprecation')
        assert MyView.deprecation == {'detail': 'This view is deprecated.', 'link': None}

    def test_class_decorator_with_link(self):
        @deprecated(detail='Deprecated.', link='https://example.com')
        class MyView(APIView):
            pass

        assert MyView.deprecation == {'detail': 'Deprecated.', 'link': 'https://example.com'}


@pytest.mark.django_db
class TestDeprecatedEndpointIntegration:
    def test_deprecated_endpoint_returns_headers(self, admin_api_client):
        response = admin_api_client.get('/api/v1/deprecated_endpoint/')

        assert response['X-Deprecated'] == 'true'
        assert 'deprecated' in response['X-Deprecated-Detail'].lower()

    def test_deprecated_endpoint_returns_link_header(self, admin_api_client):
        with override_settings(ANSIBLE_BASE_DEPRECATION_LINK='https://docs.example.com/changelog'):
            response = admin_api_client.get('/api/v1/deprecated_endpoint/')

        assert 'rel="deprecation"' in response.get('Link', '')

    def test_non_deprecated_endpoint_has_no_deprecation_headers(self, admin_api_client):
        response = admin_api_client.get('/api/v1/cows/')

        assert 'X-Deprecated' not in response
        assert 'X-Deprecated-Detail' not in response


@pytest.mark.django_db
class TestConditionalDeprecationIntegration:
    def test_no_headers_without_deprecated_param(self, admin_api_client):
        response = admin_api_client.get('/api/v1/conditional_deprecation/')

        assert 'X-Deprecated' not in response
        assert 'X-Deprecated-Detail' not in response

    def test_headers_present_with_deprecated_param(self, admin_api_client):
        response = admin_api_client.get('/api/v1/conditional_deprecation/?old_param=1')

        assert response['X-Deprecated'] == 'true'
        assert 'old_param' in response['X-Deprecated-Detail']


@pytest.mark.django_db
class TestLegacyDeprecatedIntegration:
    def test_legacy_deprecated_emits_new_headers(self, admin_api_client):
        response = admin_api_client.get('/api/v1/legacy_deprecated/')

        assert response['X-Deprecated'] == 'true'
        assert 'deprecated' in response['X-Deprecated-Detail'].lower()

    def test_legacy_deprecated_emits_warning_header(self, admin_api_client):
        response = admin_api_client.get('/api/v1/legacy_deprecated/')

        assert 'Warning' in response
        assert 'deprecated' in response['Warning'].lower()
