#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from unittest.mock import MagicMock, Mock

import pytest
from django.core.exceptions import FieldError
from rest_framework.exceptions import ParseError

from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.views import AuthenticatorViewSet
from ansible_base.rest_filters.rest_framework.order_backend import OrderByBackend


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
