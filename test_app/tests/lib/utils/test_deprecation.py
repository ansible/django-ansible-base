from django.http.response import HttpResponseBase
from django.test.client import RequestFactory
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from ansible_base.lib.utils.views.deprecation import (
    DeprecatedFieldsViewMixin,
    DeprecatedQueryParamsViewMixin,
    DeprecationSerializerMixin,
    deprecated,
    mark_deprecated,
)


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

    def test_distinct_detail_that_is_a_substring_is_not_deduplicated(self):
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'deprecated.')

        assert response['X-API-Deprecated-Detail'] == 'Endpoint is deprecated. deprecated.'

    def test_x_api_deprecated_is_idempotent(self):
        response = self._make_response()
        mark_deprecated(response, 'First.')
        mark_deprecated(response, 'Second.')

        assert response['X-API-Deprecated'] == 'true'


class TestDeprecatedSerializerFields:
    def test_empty_input_does_not_add_deprecation_warnings(self):
        class PayloadSerializer(DeprecationSerializerMixin, serializers.Serializer):
            legacy_name = serializers.CharField(required=False)
            deprecated_fields = {'legacy_name': 'legacy_name is deprecated.'}

        view = APIView()
        serializer = PayloadSerializer(data={}, context={'view': view})

        assert serializer.is_valid()
        assert not hasattr(view, '_deprecated_field_warnings')

    def test_deprecated_input_field_emits_response_headers(self):
        class PayloadSerializer(DeprecationSerializerMixin, serializers.Serializer):
            legacy_name = serializers.CharField(required=False)
            current_name = serializers.CharField(required=False)
            deprecated_fields = {
                'legacy_name': 'legacy_name is deprecated. Use current_name instead.',
            }

        class PayloadView(DeprecatedFieldsViewMixin, APIView):
            authentication_classes = []
            permission_classes = []

            def post(self, request):
                serializer = PayloadSerializer(data=request.data, context={'view': self})
                serializer.is_valid(raise_exception=True)
                return Response(serializer.validated_data)

        factory = APIRequestFactory()
        legacy_response = PayloadView.as_view()(factory.post('/', {'legacy_name': 'old'}, format='json'))
        current_response = PayloadView.as_view()(factory.post('/', {'current_name': 'new'}, format='json'))

        assert legacy_response['X-API-Deprecated'] == 'true'
        assert legacy_response['X-API-Deprecated-Detail'] == ('legacy_name is deprecated. Use current_name instead.')
        assert 'X-API-Deprecated' not in current_response


class TestDeprecatedQueryParams:
    def test_deprecated_query_parameter_emits_headers_only_when_present(self):
        class MyView(DeprecatedQueryParamsViewMixin, APIView):
            deprecated_query_params = {
                'legacy_format': 'legacy_format is deprecated. Use format=v2 instead.',
            }

            def get(self, request):
                return Response({'ok': True})

        factory = APIRequestFactory()
        legacy_response = MyView.as_view()(factory.get('/?legacy_format=v1'))
        current_response = MyView.as_view()(factory.get('/?format=v2'))

        assert legacy_response['X-API-Deprecated'] == 'true'
        assert legacy_response['X-API-Deprecated-Detail'] == ('legacy_format is deprecated. Use format=v2 instead.')
        assert 'X-API-Deprecated' not in current_response


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

    def test_class_decorator_wraps_and_preserves_action_methods(self):
        @deprecated(detail='This view is deprecated.')
        class MyView(APIView):
            def list(self, request):
                return Response({'ok': True})

        response = MyView().list(RequestFactory().get('/'))

        assert response.data == {'ok': True}
