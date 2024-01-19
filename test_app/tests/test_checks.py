from unittest import mock

from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.lib.checks import check_charfield_has_max_length


def test_check_charfield_has_max_length_fails():
    with mock.patch.object(Authenticator._meta.get_field('type'), 'max_length', new=None):
        errors = check_charfield_has_max_length(None)
        assert len(errors) == 1
        assert errors[0].id == 'ansible_base.E001'
