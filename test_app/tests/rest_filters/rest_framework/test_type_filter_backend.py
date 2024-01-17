from unittest.mock import MagicMock, Mock

import pytest
from django.core.exceptions import FieldError
from rest_framework.exceptions import ParseError

from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.views import AuthenticatorViewSet
from ansible_base.rest_filters.rest_framework.type_filter_backend import TypeFilterBackend


@pytest.mark.parametrize(
    "query",
    (
        ({}),
        ({'not_type': 'something'}),
        ({'type': 'a,b'}),
        ({'type': 'a'}),
    ),
)
@pytest.mark.django_db
def test_TypeFilterBackend_filter_query_set(query):
    filter = TypeFilterBackend()
    request = MagicMock()
    request.query_params = query
    filter.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)


def test_TypeFilterBackend_filter_query_set_exception():
    filter = TypeFilterBackend()
    request = MagicMock()
    request.query_params.items = Mock(side_effect=FieldError("missing field"))

    with pytest.raises(ParseError):
        filter.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)
