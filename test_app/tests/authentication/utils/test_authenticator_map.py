import pytest

from ansible_base.authentication.models.authenticator_map import AuthenticatorMap
from ansible_base.authentication.utils.authenticator_map import check_expansion_syntax, expand_syntax, has_expansion

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


@pytest.mark.parametrize(
    "role,organization,team,expected_results",
    [
        pytest.param(
            None,
            "Database Org",
            "My Team",
            [
                {"organization": "Database Org", "team": "My Team"},
            ],
            id="No role value",
        ),
        pytest.param(
            "Team Role",
            None,
            "My Team",
            [
                {"role": "Team Role", "team": "My Team"},
            ],
            id="No org value",
        ),
        pytest.param(
            "Team Role",
            "Database Org",
            None,
            [
                {"role": "Team Role", "organization": "Database Org"},
            ],
            id="No team value",
        ),
        pytest.param(
            "Test Role",
            "Database Org",
            "My Team",
            [
                {"role": "Test Role", "organization": "Database Org", "team": "My Team"},
            ],
            id="No Expansion",
        ),
        pytest.param(
            "Test Role",
            "Org {% for_attr_value(username) %}",
            "{% for_attr_value(member_of) %} Team",
            [
                {"role": "Test Role", "organization": "Org timmy", "team": "x Team"},
                {"role": "Test Role", "organization": "Org timmy", "team": "y Team"},
                {"role": "Test Role", "organization": "Org timmy", "team": "z Team"},
            ],
            id="Simple Happy Path",
        ),
        pytest.param(
            "{%%}",
            "Org {% for_attr_value(username) %}",
            "{% for_attr_value(member_of) %} Team",
            [
                {"organization": "Org timmy", "team": "x Team"},
                {"organization": "Org timmy", "team": "y Team"},
                {"organization": "Org timmy", "team": "z Team"},
            ],
            id="Invalid role makes it not expand",
        ),
        pytest.param(
            "Test Role",
            "Org {% (username) %}",
            "{% for_attr_value(member_of) %} Team",
            [
                {"role": "Test Role", "team": "x Team"},
                {"role": "Test Role", "team": "y Team"},
                {"role": "Test Role", "team": "z Team"},
            ],
            id="Invalid org makes it not expand",
        ),
        pytest.param(
            "Test Role",
            "Org {% for_attr_value(username) %}",
            "{% for_attr_value() %} Team",
            [
                {"role": "Test Role", "organization": "Org timmy"},
            ],
            id="Invalid team makes it not expand",
        ),
        pytest.param(
            "{% for_attr_value(junk) %}",
            "Org {% for_attr_value(username) %}",
            "{% for_attr_value(member_of) %} Team",
            [
                {"organization": "Org timmy", "team": "x Team"},
                {"organization": "Org timmy", "team": "y Team"},
                {"organization": "Org timmy", "team": "z Team"},
            ],
            id="Missing role attr makes it not expand",
        ),
        pytest.param(
            "Test Role",
            "Org {% for_attr_value(junk) %}",
            "{% for_attr_value(member_of) %} Team",
            [
                {"role": "Test Role", "team": "x Team"},
                {"role": "Test Role", "team": "y Team"},
                {"role": "Test Role", "team": "z Team"},
            ],
            id="Missing org attr makes it not expand",
        ),
        pytest.param(
            "Test Role",
            "Org {% for_attr_value(junk) %}",
            "{% for_attr_value(member_of) %} Team",
            [
                {
                    "role": "Test Role",
                    "team": "x Team",
                },
                {
                    "role": "Test Role",
                    "team": "y Team",
                },
                {
                    "role": "Test Role",
                    "team": "z Team",
                },
            ],
            id="Missing org attr makes it not expand",
        ),
        pytest.param(
            "Test Role",
            "Org {% for_attr_value(some_value) %}",
            "{% for_attr_value(member_of) %} Team {% for_attr_value(admin_of) %}",
            [
                {"role": "Test Role", "organization": "Org 1", "team": "x Team a"},
                {"role": "Test Role", "organization": "Org 1", "team": "x Team b"},
                {"role": "Test Role", "organization": "Org 1", "team": "x Team c"},
                {"role": "Test Role", "organization": "Org 1", "team": "y Team a"},
                {"role": "Test Role", "organization": "Org 1", "team": "y Team b"},
                {"role": "Test Role", "organization": "Org 1", "team": "y Team c"},
                {"role": "Test Role", "organization": "Org 1", "team": "z Team a"},
                {"role": "Test Role", "organization": "Org 1", "team": "z Team b"},
                {"role": "Test Role", "organization": "Org 1", "team": "z Team c"},
                {"role": "Test Role", "organization": "Org 2", "team": "x Team a"},
                {"role": "Test Role", "organization": "Org 2", "team": "x Team b"},
                {"role": "Test Role", "organization": "Org 2", "team": "x Team c"},
                {"role": "Test Role", "organization": "Org 2", "team": "y Team a"},
                {"role": "Test Role", "organization": "Org 2", "team": "y Team b"},
                {"role": "Test Role", "organization": "Org 2", "team": "y Team c"},
                {"role": "Test Role", "organization": "Org 2", "team": "z Team a"},
                {"role": "Test Role", "organization": "Org 2", "team": "z Team b"},
                {"role": "Test Role", "organization": "Org 2", "team": "z Team c"},
                {"role": "Test Role", "organization": "Org 3", "team": "x Team a"},
                {"role": "Test Role", "organization": "Org 3", "team": "x Team b"},
                {"role": "Test Role", "organization": "Org 3", "team": "x Team c"},
                {"role": "Test Role", "organization": "Org 3", "team": "y Team a"},
                {"role": "Test Role", "organization": "Org 3", "team": "y Team b"},
                {"role": "Test Role", "organization": "Org 3", "team": "y Team c"},
                {"role": "Test Role", "organization": "Org 3", "team": "z Team a"},
                {"role": "Test Role", "organization": "Org 3", "team": "z Team b"},
                {"role": "Test Role", "organization": "Org 3", "team": "z Team c"},
            ],
            id="Entry with 2 expansions",
        ),
        pytest.param(
            "Test Role",
            "Org {% for_attr_value(nested_groups) %}",
            "{% for_attr_value(member_of) %} Team",
            [
                {"role": "Test Role", "team": "x Team"},
                {"role": "Test Role", "team": "y Team"},
                {"role": "Test Role", "team": "z Team"},
            ],
            id="Attribute is not a list of strings",
        ),
        pytest.param(
            "System Role",
            "    ",
            None,
            [
                {"organization": "    ", "role": "System Role"},
            ],
            id="Org with just spaces",
        ),
    ],
)
@pytest.mark.django_db()
def test_expand_syntax(azuread_authenticator, role, organization, team, expected_results):
    attrs = {
        "username": "timmy",
        "member_of": ["x", "y", "z"],
        "admin_of": ["a", "b", "c"],
        "email": "timmy@example.com",
        "some_value": ['1', '2', '3'],
        "nested_groups": {"level1": ["web", "mobile"], "level2": ["api", "database"]},
    }
    map = AuthenticatorMap(
        organization=organization,
        role=role,
        team=team,
        authenticator=azuread_authenticator,
    )
    assert set({frozenset(d.items()) for d in expand_syntax(attrs, map)}) == set({frozenset(d.items()) for d in expected_results})
