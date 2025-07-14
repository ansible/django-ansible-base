import pytest

from ansible_base.authentication.utils.authenticator_map import check_expansion_syntax, has_expansion

# check_role_type is tested only though the serializer


@pytest.mark.parametrize(
    "value,expected_result",
    [
        ("a", False),
        ("{% junkj}", False),
        ("{%%}", True),
        ("Pre-string {%%}", True),
        ("Pre-string {%%} Post-STring", True),
        ("{%%} Post-String", True),
    ],
)
def test_has_expansion(value, expected_result):
    assert has_expansion(value) == expected_result


@pytest.mark.parametrize(
    "value,should_work",
    [
        ("a", True),
        ("Pre-string {%%}", False),
        ("Pre-string {% junk %} Post-STring", False),
        ("{%%} Post-String", False),
        ("Pre-string {% for_attr_value(testing) %}", True),
        ("Pre-string {% for_attr_value(testing2) %} Post-STring", True),
        ("{% for_attr_value(a) %} Post-String", True),
        ("{% for_attr_value() %} Post-String", False),
        ("{%            for_attr_value(f)       %}", True),
        ("{%       i     for_attr_value(12)       %}", False),
    ],
)
def test_check_expansion_syntax(value, should_work):
    response = check_expansion_syntax(value)
    if should_work:
        assert response is None
    else:
        assert response is not None
