import pytest

from ansible_base.authentication.authenticator_plugins.base import _field_required


class DummyField:
    def __init__(self, required, allow_null):
        if required is not None:
            self.required = required
        if allow_null is not None:
            self.allow_null = allow_null


@pytest.mark.parametrize(
    "required,allow_null,expected_result",
    [
        (None, None, True),
        (True, None, True),
        (False, None, False),
        (None, True, False),
        (None, False, True),
        (True, False, True),
        (False, False, False),
        (True, True, True),
        (False, True, False),
    ],
)
def test__field_required(required, allow_null, expected_result):
    field = DummyField(required, allow_null)
    assert _field_required(field) is expected_result
