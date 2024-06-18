from unittest import mock

import pytest
from django.db import connection

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils import claims
from test_app.tests.authentication.conftest import SYSTEM_ROLE_NAME


@pytest.mark.parametrize(
    "triggers, map_type, role, attrs, groups, exp_access_allowed, exp_is_superuser, exp_claims, exp_last_login_map_results",
    [
        pytest.param(
            {"always": {}},
            "is_superuser",
            None,
            {},
            [],
            True,
            True,
            {"team_membership": {}, "organization_membership": {}, 'rbac_roles': {'system': {'roles': {}}, 'organizations': {}}},
            [{1: True}],
            id="Set flag 'is_superuser' to True (trigger 'always')",
        ),
        pytest.param(
            {"never": {}},
            "is_superuser",
            None,
            {},
            [],
            True,
            False,
            {"team_membership": {}, "organization_membership": {}, 'rbac_roles': {'system': {'roles': {}}, 'organizations': {}}},
            [{1: False}],
            id="Set flag 'is_superuser' to False (trigger 'never')",
        ),
        pytest.param(
            {"badkey": {}},
            "is_superuser",
            None,
            {},
            [],
            True,
            None,
            {"team_membership": {}, "organization_membership": {}, 'rbac_roles': {'system': {'roles': {}}, 'organizations': {}}},
            [{1: "invalid"}],
            id="Wrong trigger, thus flag 'is_superuser' is not set, auth. map is ignored",
        ),
        pytest.param(
            {},
            "is_superuser",
            None,
            {},
            [],
            True,
            None,
            {"team_membership": {}, "organization_membership": {}, 'rbac_roles': {'system': {'roles': {}}, 'organizations': {}}},
            [{1: "skipped"}],
            id="Define no trigger, thus flag 'is_superuser' is not set",
        ),
        pytest.param(
            {"never": {}},
            "allow",
            "",
            {},
            [],
            False,
            None,
            {"team_membership": {}, "organization_membership": {}, 'rbac_roles': {'system': {'roles': {}}, 'organizations': {}}},
            [{1: False}],
            id="map_type 'allow' with trigger 'never' sets 'access_allowed' to False",
        ),
        pytest.param(
            {"always": {}},
            "team",
            'Team Member',
            {},
            [],
            True,
            None,
            {
                "organization_membership": {},
                "team_membership": {"testorg": {"testteam": True}},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {}, 'teams': {'testteam': {'roles': {'Team Member': True}}}}}},
            },
            [{1: True}],
            id="Assign 'Team Member' role to team 'testteam'",
        ),
        pytest.param(
            {"never": {}},
            "team",
            'Team Member',
            {},
            [],
            True,
            None,
            {
                "organization_membership": {},
                "team_membership": {"testorg": {"testteam": False}},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {}, 'teams': {'testteam': {'roles': {'Team Member': False}}}}}},
            },
            [{1: False}],
            id="Remove 'Team Member' role from team 'testteam'",
        ),
        pytest.param(
            {"always": {}},
            "organization",
            'Organization Member',
            {},
            [],
            True,
            None,
            {
                "organization_membership": {"testorg": True},
                "team_membership": {},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {'Organization Member': True}, 'teams': {}}}},
            },
            [{1: True}],
            id="Assign 'Organization Member' role to organization 'testorg'",
        ),
        pytest.param(
            {"never": {}},
            "organization",
            'Organization Member',
            {},
            [],
            True,
            None,
            {
                "organization_membership": {"testorg": False},
                "team_membership": {},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {'Organization Member': False}, 'teams': {}}}},
            },
            [{1: False}],
            id="Remove 'Organization Member' role from organization 'testorg'",
        ),
        pytest.param(
            {"always": {}},
            "role",
            "Team Member",
            {},
            [],
            True,
            None,
            {
                "organization_membership": {},
                "team_membership": {"testorg": {"testteam": True}},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {}, 'teams': {'testteam': {'roles': {'Team Member': True}}}}}},
            },
            [{1: True}],
            id="Assign 'Team Member' role to team 'testteam' using map_type 'role'",
        ),
        pytest.param(
            {"always": {}},
            "role",
            "Organization Member",  # Team removed from auth map in the test
            {},
            [],
            True,
            None,
            {
                "organization_membership": {"testorg": True},
                "team_membership": {},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {'Organization Member': True}, 'teams': {}}}},
            },
            [{1: True}],
            id="Assign 'Organization Member' role to organization 'testorg' using map_type 'role'",
        ),
        pytest.param(
            {"always": {}},
            "role",
            SYSTEM_ROLE_NAME,  # Team and organization removed from auth map in the test
            {},
            [],
            True,
            None,
            {"organization_membership": {}, "team_membership": {}, 'rbac_roles': {'system': {'roles': {SYSTEM_ROLE_NAME: True}}, 'organizations': {}}},
            [{1: True}],
            id="Assign System role to user",
        ),
        pytest.param(
            {"never": {}},
            "bad_map_type",
            None,
            {},
            [],
            True,
            None,
            {"organization_membership": {}, "team_membership": {}, 'rbac_roles': {'system': {'roles': {}}, 'organizations': {}}},
            [{1: False}],
            id="Wrong map type, this auth. map is ignored",
        ),
    ],
)
def test_create_claims_single_map_acl(
    shut_up_logging,
    local_authenticator_map,
    triggers,
    map_type,
    role,
    attrs,
    groups,
    exp_access_allowed,
    exp_is_superuser,
    exp_claims,
    exp_last_login_map_results,
    system_role,
):
    """
    Test a bunch of simple cases for the create_claims function.
    Anything involving groups and attributes is tested separately, below.

    Note: Team 'testteam' and Organization 'testorg' are defined in local_authenticator_map fixture!
    """
    # Customize the authenticator map for the test case
    local_authenticator_map.triggers = triggers
    local_authenticator_map.map_type = map_type
    local_authenticator_map.role = role
    if role == 'Organization Member':
        local_authenticator_map.team = ' '
    elif role == SYSTEM_ROLE_NAME:
        local_authenticator_map.team = None
        local_authenticator_map.organization = '    '

    local_authenticator_map.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, "username", attrs, groups)

    assert res["access_allowed"] == exp_access_allowed
    assert res["is_superuser"] == exp_is_superuser
    assert res["claims"] == exp_claims
    if connection.vendor != 'postgresql':
        assert res["last_login_map_results"] == exp_last_login_map_results
    else:
        assert list(res["last_login_map_results"][0].values())[0] == list(exp_last_login_map_results[0].values())[0]


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
    member_rd,
):
    """
    Test that we properly append to org_team_mapping
    """
    local_authenticator_map_1.triggers = {"never": {}}
    local_authenticator_map_1.team = "different_team"
    local_authenticator_map_1.map_type = "team"
    local_authenticator_map_1.role = member_rd.name
    local_authenticator_map_1.save()

    local_authenticator_map.map_type = "team"
    local_authenticator_map.role = member_rd.name
    local_authenticator_map.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, "username", {}, [])

    assert res["claims"] == {"team_membership": {"testorg": {"testteam": True, "different_team": False}}, "organization_membership": {}, "rbac_roles": mock.ANY}


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
def test_create_claims_revoke(local_authenticator_map, process_function, triggers, revoke, granted, default_rbac_roles_claims):
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
    assert res["claims"] == {"team_membership": {}, "organization_membership": {}, "rbac_roles": default_rbac_roles_claims}
    if revoke:
        assert res["last_login_map_results"] == [{local_authenticator_map.pk: False}]
    else:
        assert res["last_login_map_results"] == [{local_authenticator_map.pk: "skipped"}]


@pytest.mark.parametrize(
    "trigger_condition, groups, has_access",
    [
        # has_or
        ({"has_or": ["foo"]}, ["foo"], True),
        ({"has_or": ["foo"]}, ["bar"], None),
        ({"has_or": ["foo", "bar"]}, ["foo"], True),
        ({"has_or": ["foo", "bar"]}, ["bar"], True),
        ({"has_or": ["foo", "bar"]}, ["baz"], None),
        ({"has_or": ["foo", "bar"]}, ["foo", "bar"], True),
        ({"has_or": ["foo", "bar"]}, ["foo", "baz"], True),
        ({"has_or": ["foo", "bar"]}, ["bar", "baz"], True),
        ({"has_or": ["foo"]}, ["baz", "foo", "qux"], True),
        # has_and
        ({"has_and": ["foo"]}, ["foo"], True),
        ({"has_and": ["foo"]}, ["bar"], None),
        ({"has_and": ["foo", "bar"]}, ["foo", "bar"], True),
        ({"has_and": ["foo", "bar"]}, ["bar", "foo"], True),
        ({"has_and": ["foo", "bar"]}, ["foo"], None),
        ({"has_and": ["foo", "bar"]}, ["bar"], None),
        ({"has_and": ["foo", "bar"]}, ["baz"], None),
        ({"has_and": ["foo", "bar"]}, ["foo", "baz"], None),
        ({"has_and": ["foo", "bar"]}, ["bar", "baz"], None),
        # has_not
        ({"has_not": ["foo"]}, ["foo"], None),
        ({"has_not": ["foo"]}, ["bar"], True),
        ({"has_not": ["foo", "bar"]}, ["foo"], None),
        ({"has_not": ["foo", "bar"]}, ["bar"], None),
        ({"has_not": ["foo", "bar"]}, ["baz"], True),
        ({"has_not": ["foo", "bar"]}, ["foo", "bar"], None),
        ({"has_not": ["foo", "bar"]}, ["foo", "baz"], None),
        ({"has_not": ["foo", "bar"]}, ["bar", "baz"], None),
        ({"has_not": ["foo"]}, ["baz", "foo", "qux"], None),
        # has_or and has_and (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo"], True),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["bar"], None),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "bar"], True),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "baz"], True),
        # has_or and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo"], True),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["bar"], None),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], True),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "baz"], True),
        # has_and and has_not (only has_and has effect)
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo"], True),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["bar"], None),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], True),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["baz", "foo"], True),
        # has_or, has_and, and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo"], True),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["bar"], None),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["baz"], None),
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
            None,
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
            None,
            id="matches, negative",
        ),
        pytest.param(
            {"email": {"matches": "^foo@.*"}},
            {"email": "bar@example.com"},
            None,
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
            None,
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
            None,
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
            None,
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
            None,
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
            None,
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
            None,
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
            None,
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
            None,
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
            None,
            id="trigger dict attribute has empty dict, becomes 'exists', negative",
        ),
        pytest.param(
            {"email": {}},
            {},
            None,
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
            None,
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
            None,
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
            None,
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
        pytest.param(
            {"username": {"equals": "alice"}, "join_condition": "or"},
            {"username": "bob", "email": ""},
            None,
            id="user attribute is string, condition equals, join condition or, negative",
        ),
    ],
)
def test_process_user_attributes(trigger_condition, attributes, expected):
    res = claims.process_user_attributes(trigger_condition, attributes, authenticator_id=1337)
    assert res is expected


def test_update_user_claims_extra_data(user, local_authenticator_map):
    """
    We are testing a specific codepath path where update_user_claims() calls
    create_claims() and passes it extra_data (aka "attrs"). The only way for
    attrs to be used is for us to have an AuthenticatorMap attached to the
    Authenticator, which has 'triggers' with a key of 'attributes' and some
    condition value, and where the AuthenticatorUser has an extra_data with
    something meaningful in it.
    """
    local_authenticator_map.triggers = {"attributes": {"email": {"contains": "@example.com"}}}
    local_authenticator_map.save()
    authenticator = local_authenticator_map.authenticator
    # Associate the authenticator with the user
    authenticator_user = AuthenticatorUser(
        provider=authenticator,
        user=user,
        extra_data={"email": "test@example.com"},
    )
    authenticator_user.save()
    assert local_authenticator_map.authenticator == authenticator_user.provider  # sanity check
    result = claims.update_user_claims(user, authenticator, [])
    assert result is user


def test_update_user_claims_groups(user, local_authenticator_map):
    """
    Similar to above, but testing groups instead of attributes.
    """
    local_authenticator_map.triggers = {"groups": {"has_or": ["foo"]}}
    local_authenticator_map.save()
    authenticator = local_authenticator_map.authenticator
    # Associate the authenticator with the user
    authenticator_user = AuthenticatorUser(
        provider=authenticator,
        user=user,
    )
    authenticator_user.save()
    assert local_authenticator_map.authenticator == authenticator_user.provider  # sanity check
    result = claims.update_user_claims(user, authenticator, ["foo"])
    assert result is user
