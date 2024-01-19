from unittest import mock

import pytest

from ansible_base.authentication.utils import claims


@pytest.mark.parametrize(
    "triggers, map_type, attrs, groups, exp_access_allowed, exp_is_superuser, exp_is_system_auditor, exp_claims, exp_last_login_map_results",
    [
        ({"always": {}}, "is_superuser", {}, [], True, True, None, {"team_membership": {}, "organization_membership": {}}, [{1: True}]),
        ({"never": {}}, "is_superuser", {}, [], True, False, None, {"team_membership": {}, "organization_membership": {}}, [{1: False}]),
        ({"always": {}}, "is_system_auditor", {}, [], True, None, True, {"team_membership": {}, "organization_membership": {}}, [{1: True}]),
        ({"badkey": {}}, "is_system_auditor", {}, [], True, None, None, {"team_membership": {}, "organization_membership": {}}, [{1: "invalid"}]),
        ({}, "is_system_auditor", {}, [], True, None, None, {"team_membership": {}, "organization_membership": {}}, [{1: "skipped"}]),
        (
            {"always": {}, "never": {}},
            "is_superuser",
            {},
            [],
            True,
            False,
            None,
            {"team_membership": {}, "organization_membership": {}},
            [{1: False}],
        ),
        ({"never": {}}, "allow", {}, [], False, None, None, {"team_membership": {}, "organization_membership": {}}, [{1: False}]),
        (
            {"always": {}},
            "team",
            {},
            [],
            True,
            None,
            None,
            {"organization_membership": {}, "team_membership": {"testorg": {"testteam": True}}},
            [{1: True}],
        ),
        (
            {"never": {}},
            "team",
            {},
            [],
            True,
            None,
            None,
            {"organization_membership": {}, "team_membership": {"testorg": {"testteam": False}}},
            [{1: False}],
        ),
        (
            {"always": {}},
            "organization",
            {},
            [],
            True,
            None,
            None,
            {"organization_membership": {"testorg": True}, "team_membership": {}},
            [{1: True}],
        ),
        (
            {"never": {}},
            "organization",
            {},
            [],
            True,
            None,
            None,
            {"organization_membership": {"testorg": False}, "team_membership": {}},
            [{1: False}],
        ),
        ({"never": {}}, "bad_map_type", {}, [], True, None, None, {"organization_membership": {}, "team_membership": {}}, [{1: False}]),
    ],
)
def test_create_claims_single_map_acl(
    shut_up_logging,
    local_authenticator_map,
    triggers,
    map_type,
    attrs,
    groups,
    exp_access_allowed,
    exp_is_superuser,
    exp_is_system_auditor,
    exp_claims,
    exp_last_login_map_results,
):
    """
    Test a bunch of simple cases for the create_claims function.
    Anything involving groups and attributes is tested separately, below.
    """
    # Customize the authenticator map for the test case
    local_authenticator_map.triggers = triggers
    local_authenticator_map.map_type = map_type
    local_authenticator_map.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, "username", attrs, groups)

    assert res["access_allowed"] == exp_access_allowed
    assert res["is_superuser"] == exp_is_superuser
    assert res["is_system_auditor"] == exp_is_system_auditor
    assert res["claims"] == exp_claims
    assert res["last_login_map_results"] == exp_last_login_map_results


@mock.patch("ansible_base.authentication.utils.claims.logger")
def test_create_claims_bad_map_type_logged(
    logger,
    local_authenticator_map,
    shut_up_logging,
):
    """
    Test that we log properly when a bad map_type is specified.
    """
    local_authenticator_map.map_type = "bad_map_type"
    local_authenticator_map.save()

    authenticator = local_authenticator_map.authenticator
    claims.create_claims(authenticator, "username", {}, [])

    # Most of the actual logic is tested in the above test case, so we just
    # check that the log message is correct here.
    logger.error.assert_called_once_with(f"Map type bad_map_type of rule {local_authenticator_map.name} does not know how to be processed")


def test_create_claims_multiple_same_org(
    local_authenticator_map,
    local_authenticator_map_1,
):
    """
    Test that we properly append to org_team_mapping
    """
    local_authenticator_map_1.triggers = {"never": {}}
    local_authenticator_map_1.team = "different_team"
    local_authenticator_map_1.map_type = "team"
    local_authenticator_map_1.save()

    local_authenticator_map.map_type = "team"
    local_authenticator_map.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, "username", {}, [])

    assert res["claims"] == {
        "team_membership": {"testorg": {"testteam": True, "different_team": False}},
        "organization_membership": {},
    }


@pytest.mark.parametrize(
    "process_function, triggers",
    [
        ("process_groups", {"groups": {"has_or": ["foo"]}}),
        ("process_user_attributes", {"attributes": {"email": {"contains": "@example.com"}}}),
    ],
)
@pytest.mark.parametrize(
    "revoke, granted",
    [
        (True, False),
        (False, None),
    ],
)
def test_create_claims_revoke(
    local_authenticator_map,
    process_function,
    triggers,
    revoke,
    granted,
):
    """
    The "revoke" flag has a very specific meaning in the implementation.

    The following must ALL be true for the "revoke" flag to have any effect:

    1) The trigger type is either "groups" or "attributes"
    2) process_groups (for groups) or process_user_attributes (for attributes)
       returns exactly None.

    Otherwise, if the process_* function is False, the user already gets
    denied the permission. If it is True, they get granted the permission.

    We are not intending to test the process_* functions here, so we mock them
    out to return None.
    """
    # Customize the authenticator map for the test case
    local_authenticator_map.triggers = triggers
    local_authenticator_map.revoke = revoke
    local_authenticator_map.save()
    authenticator = local_authenticator_map.authenticator

    with mock.patch(f"ansible_base.authentication.utils.claims.{process_function}", return_value=None):
        res = claims.create_claims(authenticator, "username", {}, [])

    assert res["access_allowed"] is True
    assert res["is_superuser"] is granted
    assert res["is_system_auditor"] is None
    assert res["claims"] == {"team_membership": {}, "organization_membership": {}}
    if revoke:
        assert res["last_login_map_results"] == [{1: False}]
    else:
        assert res["last_login_map_results"] == [{1: "skipped"}]


@pytest.mark.parametrize(
    "trigger_condition, groups, has_access",
    [
        # has_or
        ({"has_or": ["foo"]}, ["foo"], True),
        ({"has_or": ["foo"]}, ["bar"], False),
        ({"has_or": ["foo", "bar"]}, ["foo"], True),
        ({"has_or": ["foo", "bar"]}, ["bar"], True),
        ({"has_or": ["foo", "bar"]}, ["baz"], False),
        ({"has_or": ["foo", "bar"]}, ["foo", "bar"], True),
        ({"has_or": ["foo", "bar"]}, ["foo", "baz"], True),
        ({"has_or": ["foo", "bar"]}, ["bar", "baz"], True),
        ({"has_or": ["foo"]}, ["baz", "foo", "qux"], True),
        # has_and
        ({"has_and": ["foo"]}, ["foo"], True),
        ({"has_and": ["foo"]}, ["bar"], False),
        ({"has_and": ["foo", "bar"]}, ["foo", "bar"], True),
        ({"has_and": ["foo", "bar"]}, ["bar", "foo"], True),
        ({"has_and": ["foo", "bar"]}, ["foo"], False),
        ({"has_and": ["foo", "bar"]}, ["bar"], False),
        ({"has_and": ["foo", "bar"]}, ["baz"], False),
        ({"has_and": ["foo", "bar"]}, ["foo", "baz"], False),
        ({"has_and": ["foo", "bar"]}, ["bar", "baz"], False),
        # has_not
        ({"has_not": ["foo"]}, ["foo"], False),
        ({"has_not": ["foo"]}, ["bar"], True),
        ({"has_not": ["foo", "bar"]}, ["foo"], False),
        ({"has_not": ["foo", "bar"]}, ["bar"], False),
        ({"has_not": ["foo", "bar"]}, ["baz"], True),
        ({"has_not": ["foo", "bar"]}, ["foo", "bar"], False),
        ({"has_not": ["foo", "bar"]}, ["foo", "baz"], False),
        ({"has_not": ["foo", "bar"]}, ["bar", "baz"], False),
        ({"has_not": ["foo"]}, ["baz", "foo", "qux"], False),
        # has_or and has_and (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo"], True),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["bar"], False),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "bar"], True),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "baz"], True),
        # has_or and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo"], True),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["bar"], False),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], True),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "baz"], True),
        # has_and and has_not (only has_and has effect)
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo"], True),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["bar"], False),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], True),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["baz", "foo"], True),
        # has_or, has_and, and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo"], True),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["bar"], False),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["baz"], False),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo", "bar"], True),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo", "baz"], True),
        # None of has_or, has_and, or has_not
        ({}, ["foo"], None),
        ({"foo": "bar"}, ["foo"], None),
    ],
)
def test_process_groups(trigger_condition, groups, has_access):
    """
    Test the process_groups function.
    """
    res = claims.process_groups(trigger_condition, groups, authenticator_id=1337)
    assert res is has_access


@pytest.mark.parametrize(
    "current_access, new_access, condition, expected",
    [
        (None, True, "or", True),
        (None, True, "and", True),
        (None, False, "or", False),
        (None, False, "and", False),
        (True, True, "or", True),
        (True, True, "and", True),
        (True, False, "or", True),
        (True, False, "and", False),
        (False, True, "or", True),
        (False, True, "and", False),
        (False, False, "or", False),
        (False, False, "and", False),
        (True, False, "invalid", None),  # any invalid condition returns None
    ],
)
def test_has_access_with_join(current_access, new_access, condition, expected):
    """
    Test the has_access_with_join function which is effectively two truth tables
    and None.
    """
    res = claims.has_access_with_join(current_access, new_access, condition)
    assert res is expected


@pytest.mark.parametrize(
    "trigger_condition, attributes, expected",
    [
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": "foo@example.com"},
            True,
            id="equals, positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": "foo@example.org"},
            False,
            id="equals, negative",
        ),
        pytest.param(
            {"email": {"matches": ".*@ex.*"}},
            {"email": "foo@example.com"},
            True,
            id="matches, positive",
        ),
        pytest.param(
            {"email": {"matches": "^foo@.*"}},
            {"email": "foo@example.com"},
            True,
            id="matches, start of line, positive",
        ),
        pytest.param(
            {"email": {"matches": "foo@.*"}},
            {"email": "bar@example.com"},
            False,
            id="matches, negative",
        ),
        pytest.param(
            {"email": {"matches": "^foo@.*"}},
            {"email": "bar@example.com"},
            False,
            id="matches, start of line, negative",
        ),
        pytest.param(
            {"email": {"contains": "@example.com"}},
            {"email": "foo@example.com"},
            True,
            id="contains, positive",
        ),
        pytest.param(
            {"email": {"contains": "@example.com"}},
            {"email": "foo@example.org"},
            False,
            id="contains, negative",
        ),
        pytest.param(
            {"email": {"ends_with": "@example.com"}},
            {"email": "foo@example.com"},
            True,
            id="ends_with, positive",
        ),
        pytest.param(
            {"email": {"ends_with": "@example.com"}},
            {"email": "foo@example.org"},
            False,
            id="ends_with, negative",
        ),
        pytest.param(
            {"email": {"in": "omg hey foo@example.com bye"}},
            {"email": "foo@example.com"},
            True,
            id="in, positive",
        ),
        pytest.param(
            {"email": {"in": "omg hey foo@example.com bye"}},
            {"email": "foo@example.org"},
            False,
            id="in, negative",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org"},
            False,
            id="'and' join_condition, missing one attribute, negative",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org", "favorite_color": "red"},
            False,
            id="'and' join_condition, two false conditions, negative",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org", "favorite_color": "teal"},
            False,
            id="'and' join_condition, one false condition, negative",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "teal"},
            True,
            id="'and' join_condition, positive",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "join_condition": "or",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "teal"},
            True,
            id="'or' join_condition, both conditions true, positive",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "join_condition": "or",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "red"},
            True,
            id="'or' join_condition, one condition true, positive",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "red"},
            True,
            id="implicit 'or' join_condition, one condition true, positive",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org", "favorite_color": "red"},
            False,
            id="implicit 'or' join_condition, both conditions false, negative",
        ),
        pytest.param(
            {
                "email": {"in": "omg hey foo@example.com bye"},
                "join_condition": "or",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org", "favorite_color": "red"},
            False,
            id="'or' join_condition, both conditions false, negative",
        ),
        pytest.param(
            {"email": {"invalid": "omg hey foo@example.com bye"}},
            {"email": "foo@example.org"},
            None,
            id="invalid predicate in trigger conditions returns None",
        ),
        pytest.param(
            {"email": {}},
            {"email": "foo@example.org"},
            True,
            id="trigger dict attribute has empty dict, becomes 'exists', positive",
        ),
        pytest.param(
            {"email": {}},
            {"favorite_color": "teal"},
            False,
            id="trigger dict attribute has empty dict, becomes 'exists', negative",
        ),
        pytest.param(
            {"email": {}},
            {},
            False,
            id="trigger dict attribute has empty dict, becomes 'exists', empty attributes, negative",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}},
            {"favorite_color": "teal"},
            True,
            id="trigger dict attributes have empty dicts, becomes 'exists', implicit 'or', positive",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "or"},
            {"favorite_color": "teal"},
            True,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'or', positive",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "and"},
            {"favorite_color": "teal"},
            False,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'and', negative",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "and"},
            {"favorite_color": "teal", "email": "foo@example.com"},
            True,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'and', positive",
        ),
        pytest.param(
            {"email": {"contains": "example"}},
            {"email": None},
            None,
            id="user attribute is None, no predicate checks, returns None",
        ),
        pytest.param(
            {"email": {}},
            {"email": None},
            True,
            id="user attribute is None, exists check still works, negative",
        ),
        # It can take a list, and in that case the same join_condition works internally too
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": ["bar@example.com", "baz@example.com"]},
            False,
            id="user attribute is list, no matches, negative",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": ["bar@example.com", "foo@example.com"]},
            True,
            id="user attribute is list, one match, implicit 'or', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": ["bar@example.com", "foo@example.com"]},
            False,
            id="user attribute is list, one match, explicit 'and', negative",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": ["foo@example.com", "foo@example.com"]},
            True,
            id="user attribute is list, all matches, explicit 'and', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": ["foo@example.com", "foo@example.com"]},
            True,
            id="user attribute is list, all matches, explicit 'or', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": []},
            None,
            id="user attribute is empty list, explicit 'and', returns None",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": []},
            None,
            id="user attribute is empty list, explicit 'or', returns None",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": ["foo@example.com", "bar@example.com"]},
            True,
            id="user attribute is list, explicit 'or', second match is false, positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "invalid"},
            {"email": ["foo@example.com", "bar@example.com"]},
            True,
            id="join condition is invalid, defaults to or",
        ),
    ],
)
def test_process_user_attributes(trigger_condition, attributes, expected):
    res = claims.process_user_attributes(trigger_condition, attributes, authenticator_id=1337)
    assert res is expected
