from unittest.mock import MagicMock

from ansible_base.common.utils import models


def test_get_type_for_model():
    dummy_model = MagicMock()
    dummy_model._meta.concrete_model._meta.object_name = 'SnakeCaseString'

    assert models.get_type_for_model(dummy_model) == 'snake_case_string'
