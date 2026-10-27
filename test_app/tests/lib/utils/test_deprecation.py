import pytest
from django.http.response import HttpResponseBase
from django.test.client import RequestFactory
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from ansible_base.lib.utils.views.deprecation import (
    DEFAULT_DEPRECATION_MESSAGE,
    DeprecatedFieldsViewMixin,
    DeprecatedQueryParamsViewMixin,
    DeprecationSerializerMixin,
    deprecated,
    mark_deprecated,
)


class TestMarkDeprecated:
    def _make_response(self):
        """Create a response with no preexisting deprecation headers."""
        return HttpResponseBase()

    def test_sets_all_headers(self):
        """A new response receives both the deprecation flag and the supplied detail."""
        response = self._make_response()
        mark_deprecated(response, 'This endpoint is deprecated.')

        assert response['X-API-Deprecated'] == 'true'
        assert response['X-API-Deprecated-Detail'] == 'This endpoint is deprecated.'

    def test_appends_trailing_period(self):
        """Details without a trailing period are normalized before becoming headers."""
        response = self._make_response()
        mark_deprecated(response, 'Missing period')

        assert response['X-API-Deprecated-Detail'] == 'Missing period.'

    def test_whitespace(self):
        """Whitespace-only details fall back to the generic deprecation message."""
        response = self._make_response()
        mark_deprecated(response, ' ')

        assert response['X-API-Deprecated-Detail'] == str(DEFAULT_DEPRECATION_MESSAGE)

    def test_empty_strings(self):
        """Empty details fall back to the generic deprecation message."""
        response = self._make_response()
        mark_deprecated(response, '')

        assert response['X-API-Deprecated-Detail'] == str(DEFAULT_DEPRECATION_MESSAGE)

    def test_multiple_calls_accumulate_details(self):
        """Distinct deprecation messages accumulate in one detail header."""
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'The old_param parameter is deprecated.')

        assert response['X-API-Deprecated-Detail'] == 'Endpoint is deprecated. The old_param parameter is deprecated.'

    def test_duplicate_details_not_repeated(self):
        """Applying the same message twice does not duplicate the header detail."""
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'Endpoint is deprecated.')

        assert response['X-API-Deprecated-Detail'] == 'Endpoint is deprecated.'

    def test_distinct_detail_that_is_a_substring_is_not_deduplicated(self):
        """A message contained within another remains a distinct deprecation detail."""
        response = self._make_response()
        mark_deprecated(response, 'Endpoint is deprecated.')
        mark_deprecated(response, 'deprecated.')

        assert response['X-API-Deprecated-Detail'] == 'Endpoint is deprecated. deprecated.'

    def test_x_api_deprecated_is_idempotent(self):
        """Adding multiple details leaves the deprecation flag set to true."""
        response = self._make_response()
        mark_deprecated(response, 'First.')
        mark_deprecated(response, 'Second.')

        assert response['X-API-Deprecated'] == 'true'


class TestDeprecatedSerializerFields:
    @pytest.fixture(autouse=True)
    def isolate_deprecated_field_registry(self, monkeypatch):
        """Keep serializer registrations local to each test."""
        monkeypatch.setattr('ansible_base.lib.utils.views.deprecation._DEPRECATED_FIELD_REGISTRY', {})

    def test_empty_input_does_not_add_deprecation_warnings(self):
        """An empty payload does not trigger warnings for absent deprecated fields."""

        class PayloadSerializer(DeprecationSerializerMixin, serializers.Serializer):
            legacy_name = serializers.CharField(required=False)
            deprecated_fields = {'legacy_name': 'legacy_name is deprecated.'}

        view = APIView()
        serializer = PayloadSerializer(data={}, context={'view': view})

        assert serializer.is_valid()
        assert not hasattr(view, '_deprecated_field_warnings')

    @pytest.mark.parametrize('many', [False, True])
    def test_deprecated_input_field_emits_response_headers(self, many):
        """Single and list payloads emit headers only when deprecated fields are submitted."""

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
                """Validate the submitted payload and return its validated data."""
                serializer = PayloadSerializer(data=request.data, many=many, context={'view': self})
                serializer.is_valid(raise_exception=True)
                return Response(serializer.validated_data)

        legacy_data = {'legacy_name': 'old'}
        current_data = {'current_name': 'new'}
        if many:
            legacy_data = [current_data, legacy_data, legacy_data]
            current_data = [current_data]

        factory = APIRequestFactory()
        legacy_response = PayloadView.as_view()(factory.post('/', legacy_data, format='json'))
        current_response = PayloadView.as_view()(factory.post('/', current_data, format='json'))

        assert legacy_response.status_code == 200
        assert current_response.status_code == 200
        assert legacy_response.data == legacy_data
        assert current_response.data == current_data
        assert legacy_response['X-API-Deprecated'] == 'true'
        assert legacy_response['X-API-Deprecated-Detail'] == ('legacy_name is deprecated. Use current_name instead.')
        assert 'X-API-Deprecated' not in current_response
        assert 'X-API-Deprecated-Detail' not in current_response

    @pytest.mark.parametrize('many', [False, True])
    def test_nested_deprecated_field_emits_response_headers(self, many):
        """Nested serializer children propagate warnings through the parent's view context."""

        class ChildSerializer(DeprecationSerializerMixin, serializers.Serializer):
            legacy_name = serializers.CharField(required=False)
            current_name = serializers.CharField(required=False)
            deprecated_fields = {'legacy_name': 'legacy_name is deprecated.'}

        class PayloadSerializer(serializers.Serializer):
            payload = ChildSerializer(many=many)

        class PayloadView(DeprecatedFieldsViewMixin, APIView):
            authentication_classes = []
            permission_classes = []

            def post(self, request):
                """Validate nested payloads so child warnings can reach response finalization."""
                serializer = PayloadSerializer(data=request.data, context={'view': self})
                serializer.is_valid(raise_exception=True)
                return Response(serializer.validated_data)

        legacy_data = {'legacy_name': 'old'}
        current_data = {'current_name': 'new'}
        if many:
            legacy_data = [current_data, legacy_data, legacy_data]
            current_data = [current_data]

        factory = APIRequestFactory()
        legacy_response = PayloadView.as_view()(factory.post('/', {'payload': legacy_data}, format='json'))
        current_response = PayloadView.as_view()(factory.post('/', {'payload': current_data}, format='json'))

        assert legacy_response.status_code == 200
        assert current_response.status_code == 200
        assert legacy_response.data == {'payload': legacy_data}
        assert current_response.data == {'payload': current_data}
        assert legacy_response['X-API-Deprecated'] == 'true'
        assert legacy_response['X-API-Deprecated-Detail'] == 'legacy_name is deprecated.'
        assert 'X-API-Deprecated' not in current_response
        assert 'X-API-Deprecated-Detail' not in current_response

    @pytest.mark.parametrize('data', [None, [], ['legacy_name'], 'legacy_name', 1])
    def test_non_mapping_input_is_rejected_without_deprecation_warnings(self, data):
        """Invalid payloads reach DRF validation without creating false deprecation warnings."""

        class PayloadSerializer(DeprecationSerializerMixin, serializers.Serializer):
            legacy_name = serializers.CharField(required=False)
            deprecated_fields = {'legacy_name': 'legacy_name is deprecated.'}

        view = APIView()
        serializer = PayloadSerializer(data=data, context={'view': view})

        assert not serializer.is_valid()
        assert serializer.errors
        assert not hasattr(view, '_deprecated_field_warnings')


class TestDeprecatedQueryParams:
    def test_deprecated_query_parameter_emits_headers_only_when_present(self):
        """Only requests containing a deprecated query parameter receive its warning."""

        class MyView(DeprecatedQueryParamsViewMixin, APIView):
            deprecated_query_params = {
                'legacy_format': 'legacy_format is deprecated. Use format=v2 instead.',
            }

            def get(self, request):
                """Return a response for query-parameter deprecation checks."""
                return Response({'ok': True})

        factory = APIRequestFactory()
        legacy_response = MyView.as_view()(factory.get('/?legacy_format=v1'))
        current_response = MyView.as_view()(factory.get('/?format=v2'))

        assert legacy_response['X-API-Deprecated'] == 'true'
        assert legacy_response['X-API-Deprecated-Detail'] == ('legacy_format is deprecated. Use format=v2 instead.')
        assert 'X-API-Deprecated' not in current_response


class TestDeprecatedDecoratorMethod:
    def test_method_decorator_sets_headers(self):
        """A decorated handler adds deprecation headers to its returned response."""

        class MyView(APIView):
            @deprecated(detail='The get method is deprecated.')
            def get(self, request):
                """Return a response for method-level deprecation checks."""
                return Response({'ok': True})

        view = MyView()
        factory = RequestFactory()
        request = factory.get('/')
        response = view.get(request)

        assert response['X-API-Deprecated'] == 'true'
        assert response['X-API-Deprecated-Detail'] == 'The get method is deprecated.'

    def test_method_decorator_preserves_function_name(self):
        """Decorating a handler preserves its original name and docstring."""

        class MyView(APIView):
            @deprecated(detail='Deprecated.')
            def get(self, request):
                """Original docstring."""
                return Response({})

        assert MyView.get.__name__ == 'get'
        assert MyView.get.__doc__ == 'Original docstring.'

    def test_method_decorator_sets_deprecation_dict(self):
        """A decorated handler exposes its detail as deprecation metadata."""

        class MyView(APIView):
            @deprecated(detail='Test detail.')
            def get(self, request):
                """Provide a handler on which to inspect deprecation metadata."""
                return Response({})

        assert hasattr(MyView.get, 'deprecation')
        assert MyView.get.deprecation == {'detail': 'Test detail.'}


class TestDeprecatedDecoratorClass:
    def test_class_decorator_sets_deprecation_dict(self):
        """A decorated view class exposes the supplied deprecation metadata."""

        @deprecated(detail='This view is deprecated.')
        class MyView(APIView):
            pass

        assert hasattr(MyView, 'deprecation')
        assert MyView.deprecation == {'detail': 'This view is deprecated.'}

    def test_class_decorator_wraps_and_preserves_action_methods(self):
        """Class-level deprecation preserves the behavior of wrapped DRF actions."""

        @deprecated(detail='This view is deprecated.')
        class MyView(APIView):
            def list(self, request):
                """Return a response from the action wrapped by the class decorator."""
                return Response({'ok': True})

        response = MyView().list(RequestFactory().get('/'))

        assert response.data == {'ok': True}
