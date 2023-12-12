from unittest.mock import MagicMock, Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist, FieldError, ValidationError
from rest_framework.exceptions import ParseError, PermissionDenied

from ansible_base.models import Authenticator, AuthenticatorMap
from ansible_base.utils.rest_filters import FieldLookupBackend, OrderByBackend, TypeFilterBackend, get_field_from_path
from ansible_base.views import AuthenticatorViewSet

User = get_user_model()


def test_filters_related():
    field_lookup = FieldLookupBackend()
    lookup = '__'.join(['created_by', 'pk'])
    field, new_lookup = field_lookup.get_field_from_lookup(Authenticator, lookup)


def test_filters_no_lookup():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ParseError):
        _, _ = field_lookup.get_field_from_lookup(Authenticator, '')


def test_invalid_filter_key():
    field_lookup = FieldLookupBackend()
    # FieldDoesNotExist is caught and converted to ParseError by filter_queryset
    with pytest.raises(FieldDoesNotExist) as excinfo:
        field_lookup.value_to_python(Authenticator, 'created_by.gibberish', 'foo')
    assert 'has no field named' in str(excinfo)


def test_invalid_field_hop():
    with pytest.raises(ParseError) as excinfo:
        get_field_from_path(Authenticator, 'created_by__last_name__user')
    assert 'No related model for' in str(excinfo)


def test_invalid_order_by_key():
    field_order_by = OrderByBackend()
    with pytest.raises(ParseError) as excinfo:
        [f for f in field_order_by._validate_ordering_fields(Authenticator, ('modified_by.junk',))]
    assert 'has no field named' in str(excinfo)


@pytest.mark.parametrize(u"empty_value", [u'', ''])
def test_empty_in(empty_value):
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError) as excinfo:
        field_lookup.value_to_python(Authenticator, 'created_by__username__in', empty_value)
    assert 'empty value for __in' in str(excinfo.value)


@pytest.mark.parametrize(u"valid_value", [u'foo', u'foo,'])
def test_valid_in(valid_value):
    field_lookup = FieldLookupBackend()
    value, new_lookup, _ = field_lookup.value_to_python(Authenticator, 'created_by__username__in', valid_value)
    assert 'foo' in value


def test_invalid_field():
    invalid_field = u"ヽヾ"
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError) as excinfo:
        field_lookup.value_to_python(Authenticator, invalid_field, 'foo')
    assert 'is not an allowed field name. Must be ascii encodable.' in str(excinfo.value)


def test_valid_iexact():
    field_lookup = FieldLookupBackend()
    value, new_lookup, _ = field_lookup.value_to_python(Authenticator, 'created_by__username__iexact', 'foo')
    assert 'foo' in value


def test_invalid_iexact():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError) as excinfo:
        field_lookup.value_to_python(Authenticator, 'id__iexact', '1')
    assert 'is not a text field and cannot be filtered by case-insensitive search' in str(excinfo.value)


@pytest.mark.parametrize('lookup_suffix', ['', 'contains', 'startswith', 'in'])
def test_filter_on_password_field(lookup_suffix):
    # Make the type field of Authenticator a PASSWORD_FIELD
    setattr(Authenticator, 'PASSWORD_FIELDS', ('type'))
    field_lookup = FieldLookupBackend()
    lookup = '__'.join(filter(None, ['type', lookup_suffix]))
    with pytest.raises(PermissionDenied) as excinfo:
        field, new_lookup = field_lookup.get_field_from_lookup(Authenticator, lookup)
    assert 'not allowed' in str(excinfo.value)


@pytest.mark.parametrize(
    'model, query',
    [
        (Authenticator, 'configuration__icontains'),
    ],
)
def test_filter_sensitive_fields_and_relations(model, query):
    field_lookup = FieldLookupBackend()
    with pytest.raises(PermissionDenied) as excinfo:
        field, new_lookup = field_lookup.get_field_from_lookup(model, query)
    assert 'not allowed' in str(excinfo.value)


@pytest.mark.parametrize(
    'value,result',
    (
        (1, 1),
        (None, None),
        ('none', None),
        ('null', None),
        (-1, -1),
    ),
)
def test_to_python_related(value, result):
    field_lookup = FieldLookupBackend()
    assert field_lookup.to_python_related(value) == result


def test_to_python_related_exception():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError):
        field_lookup.to_python_related('random')


def test_value_to_python_for_field_boolean_field():
    field_lookup = FieldLookupBackend()
    assert field_lookup.value_to_python_for_field(Authenticator._meta.get_field('remove_users'), True) is True


def test_value_to_python_for_field_fk_field_exception():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ParseError):
        field_lookup.value_to_python_for_field(AuthenticatorMap._meta.get_field('authenticator'), True)


def test_OrderByBackend_get_default_ordering_no_order():
    order_by = OrderByBackend()
    order_by.get_default_ordering(AuthenticatorViewSet)


def test_OrderByBackend_get_default_ordering_order():
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
def test_OrderByBackend_filter_query_set(query):
    order_by = OrderByBackend()
    request = MagicMock()
    request.query_params = query

    order_by.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)


def test_OrderByBackend_filter_query_set_exception():
    order_by = OrderByBackend()
    request = MagicMock()
    request.query_params = {}
    order_by.get_default_ordering = Mock(side_effect=FieldError("missing field"))

    with pytest.raises(ParseError):
        order_by.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)


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


@pytest.mark.parametrize("exception", ((ValidationError("")), (FieldError(""))))
def test_FieldLookupBackend_filter_queryset_exception(exception):
    filter = FieldLookupBackend()
    request = MagicMock()
    request.query_params.lists = Mock(side_effect=exception)

    with pytest.raises(ParseError):
        filter.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)


@pytest.mark.parametrize(
    "query",
    (
        (()),
        ((('page_size', [10]),)),
        ((('id__int', [10]),)),
        ((('or__id', [10]),)),
        ((('not__id', [10]),)),
        ((('chain__id', [10]),)),
        ((('authenticator__search', ['find_me']),)),
        ((('authenticator__search', ['find_me,also_me']),)),
    ),
)
def test_FieldLookupBackend_filter_queryset(query):
    filter = FieldLookupBackend()
    request = MagicMock()
    iterator = MagicMock()
    iterator.__iter__.return_value = query
    request.query_params.lists.return_value = iterator

    filter.filter_queryset(request, AuthenticatorMap.objects.all(), AuthenticatorViewSet)
