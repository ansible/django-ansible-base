from base64 import b64encode

import pytest

from ansible_base.authentication.models.authenticator_user import b64_encode_binary_data_in_dict


@pytest.mark.parametrize(
    "input,output",
    [
        (True, True),
        (1, 1),
        ('hi', 'hi'),
        (b'hi', b64encode(b'hi').decode('utf-8')),
        (['a', b'b', 'c'], ['a', b64encode(b'b').decode('utf-8'), 'c']),
        ({'a': b'b'}, {'a': b64encode(b'b').decode('utf-8')}),
        (
            {"a": b'b', 'c': ['d', b'e'], 'f': {'g': b'h'}},
            {"a": b64encode(b'b').decode('utf-8'), 'c': ['d', b64encode(b'e').decode('utf-8')], 'f': {'g': b64encode(b'h').decode('utf-8')}},
        ),
    ],
)
def test_b64_encode_binary_data_in_dict(input, output):
    assert b64_encode_binary_data_in_dict(input) == output
