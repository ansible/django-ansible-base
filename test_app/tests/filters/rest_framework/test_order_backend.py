from unittest.mock import MagicMock, Mock

import pytest
from django.core.exceptions import FieldError
from rest_framework.exceptions import ParseError

from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.views import AuthenticatorViewSet
from ansible_base.filters.rest_framework.order_backend import OrderByBackend


def test_get_default_ordering_no_order():
    order_by = OrderByBackend()
    order_by.get_default_ordering(AuthenticatorViewSet)


def test_get_default_ordering_order():
    order_by = OrderByBackend()
    view = AuthenticatorViewSet()
    setattr(view, 'ordering', 'id')
    order_by.get_default_ordering(view)


@pytest.mark.parametrize(
    ("query"),
    (
        ({'order': 'id'}),
        ({'order': 'id,name'}),
        ({'order': '-id'}),
        ({'not_order': 'id'}),
    ),
)
def test_filter_query_set(query):
    order_by = OrderByBackend()
    request = MagicMock()
    request.query_params = query

    order_by.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)


def test_filter_query_set_exception():
    order_by = OrderByBackend()
    request = MagicMock()
    request.query_params = {}
    order_by.get_default_ordering = Mock(side_effect=FieldError("missing field"))

    with pytest.raises(ParseError):
        order_by.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)
