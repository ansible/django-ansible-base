import pytest
from rest_framework.exceptions import ParseError, PermissionDenied

from ansible_base.authentication.models import Authenticator
from ansible_base.rest_filters.utils import get_field_from_path
from test_app.models import EncryptionModel


def test_invalid_field_hop():
    with pytest.raises(ParseError) as excinfo:
        get_field_from_path(Authenticator, 'created_by__last_name__user')
    assert 'No related model for' in str(excinfo)


def test_invalid_field_filter():
    test_field = EncryptionModel.encrypted_fields[0]
    with pytest.raises(PermissionDenied) as excinfo:
        get_field_from_path(EncryptionModel, test_field)

    assert f"Filtering on field {test_field} is not allowed." in str(excinfo)
