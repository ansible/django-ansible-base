import pytest
from rest_framework.exceptions import ParseError

from ansible_base.models import Authenticator
from ansible_base.utils.filters import get_field_from_path


def test_invalid_field_hop():
    with pytest.raises(ParseError) as excinfo:
        get_field_from_path(Authenticator, 'created_by__last_name__user')
    assert 'No related model for' in str(excinfo)
