from functools import partial
from unittest.mock import MagicMock

import pytest
from django.test.utils import override_settings

from ansible_base.lib.utils import models


def test_get_type_for_model():
    dummy_model = MagicMock()
    dummy_model._meta.concrete_model._meta.object_name = 'SnakeCaseString'

    assert models.get_type_for_model(dummy_model) == 'snake_case_string'


@pytest.mark.django_db
def test_system_user_unset():
    with override_settings(SYSTEM_USERNAME=None):
        assert models.get_system_user() is None


@pytest.mark.django_db
def test_system_user_set(system_user):
    assert models.get_system_user() == system_user


@pytest.mark.django_db
def test_system_user_set_but_no_user(expected_log):
    system_username = 'LittleTimmy'
    with override_settings(SYSTEM_USERNAME=system_username):
        expected_log = partial(expected_log, "ansible_base.lib.utils.models.logger")
        with expected_log('error', f'is set to {system_username} but no user with that username exists'):
            assert models.get_system_user() is None
