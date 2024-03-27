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
