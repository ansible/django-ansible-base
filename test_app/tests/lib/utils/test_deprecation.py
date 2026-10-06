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
        mark_deprecated(response, 'This endpoint is deprecated.')

        assert response['X-API-Deprecated'] == 'true'
        assert response['X-API-Deprecated-Detail'] == 'This endpoint is deprecated.'

    def test_appends_trailing_period(self):
        response = self._make_response()
        mark_deprecated(response, 'Missing period')

        assert response['X-API-Deprecated-Detail'] == 'Missing period.'

    def test_multiple_calls_accumulate_details(self):
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'The old_param parameter is deprecated.')

        assert response['X-API-Deprecated-Detail'] == 'Endpoint is deprecated. The old_param parameter is deprecated.'

    def test_duplicate_details_not_repeated(self):
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'Endpoint is deprecated.')

        assert response['X-API-Deprecated-Detail'] == 'Endpoint is deprecated.'

    def test_x_api_deprecated_is_idempotent(self):
        response = self._make_response()
        mark_deprecated(response, 'First.')
        mark_deprecated(response, 'Second.')

        assert response['X-API-Deprecated'] == 'true'


class TestDeprecatedDecoratorMethod:
    def test_method_decorator_sets_headers(self):
        class MyView(APIView):
            @deprecated(detail='The get method is deprecated.')
            def get(self, request):
                return Response({'ok': True})

        view = MyView()
        factory = RequestFactory()
        request = factory.get('/')
        response = view.get(request)

        assert response['X-API-Deprecated'] == 'true'
        assert response['X-API-Deprecated-Detail'] == 'The get method is deprecated.'

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
            @deprecated(detail='Test detail.')
            def get(self, request):
                return Response({})

        assert hasattr(MyView.get, 'deprecation')
        assert MyView.get.deprecation == {'detail': 'Test detail.'}


class TestDeprecatedDecoratorClass:
    def test_class_decorator_sets_deprecation_dict(self):
        @deprecated(detail='This view is deprecated.')
        class MyView(APIView):
            pass

        assert hasattr(MyView, 'deprecation')
        assert MyView.deprecation == {'detail': 'This view is deprecated.'}


