import hashlib
import logging
from unittest import mock

import pytest
from django.db import connection

from ansible_base.authentication.models import AuthenticatorMap, AuthenticatorUser
from ansible_base.authentication.utils import claims
from test_app.tests.authentication.conftest import ORG_ADMIN_ROLE_NAME, ORG_MEMBER_ROLE_NAME, SYSTEM_ROLE_NAME, TEAM_ADMIN_ROLE_NAME, TEAM_MEMBER_ROLE_NAME


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
            [{1: True, 'enabled': True}],
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
            [{1: False, 'enabled': True}],
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
            [{1: "invalid", 'enabled': True}],
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
            [{1: "skipped", 'enabled': True}],
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
            [{1: False, 'enabled': True}],
            id="map_type 'allow' with trigger 'never' sets 'access_allowed' to False",
        ),
        pytest.param(
            {"always": {}},
            "allow",
            "",
            {},
            [],
            True,
            None,
            {"team_membership": {}, "organization_membership": {}, 'rbac_roles': {'system': {'roles': {}}, 'organizations': {}}},
            [{1: True, 'enabled': True}],
            id="map_type 'allow' with trigger 'always' sets 'access_allowed' to True (AAP-45394)",
        ),
        pytest.param(
            {"always": {}},
            "team",
            TEAM_MEMBER_ROLE_NAME,
            {},
            [],
            True,
            None,
            {
                "organization_membership": {},
                "team_membership": {"testorg": {"testteam": True}},
                'rbac_roles': {
                    'system': {'roles': {}},
                    'organizations': {'testorg': {'roles': {}, 'teams': {'testteam': {'roles': {TEAM_MEMBER_ROLE_NAME: True}}}}},
                },
            },
            [{1: True, 'enabled': True}],
            id=f"Assign {TEAM_MEMBER_ROLE_NAME} role to team 'testteam'",
        ),
        pytest.param(
            {"never": {}},
            "team",
            TEAM_MEMBER_ROLE_NAME,
            {},
            [],
            True,
            None,
            {
                "organization_membership": {},
                "team_membership": {"testorg": {"testteam": False}},
                'rbac_roles': {
                    'system': {'roles': {}},
                    'organizations': {'testorg': {'roles': {}, 'teams': {'testteam': {'roles': {TEAM_MEMBER_ROLE_NAME: False}}}}},
                },
            },
            [{1: False, 'enabled': True}],
            id=f"Remove {TEAM_MEMBER_ROLE_NAME} role from team 'testteam'",
        ),
        pytest.param(
            {"always": {}},
            "organization",
            ORG_MEMBER_ROLE_NAME,
            {},
            [],
            True,
            None,
            {
                "organization_membership": {"testorg": True},
                "team_membership": {},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {ORG_MEMBER_ROLE_NAME: True}, 'teams': {}}}},
            },
            [{1: True, 'enabled': True}],
            id=f"Assign {ORG_MEMBER_ROLE_NAME} role to organization 'testorg'",
        ),
        pytest.param(
            {"never": {}},
            "organization",
            ORG_MEMBER_ROLE_NAME,
            {},
            [],
            True,
            None,
            {
                "organization_membership": {"testorg": False},
                "team_membership": {},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {ORG_MEMBER_ROLE_NAME: False}, 'teams': {}}}},
            },
            [{1: False, 'enabled': True}],
            id=f"Remove {ORG_MEMBER_ROLE_NAME} role from organization 'testorg'",
        ),
        pytest.param(
            {"always": {}},
            "role",
            TEAM_MEMBER_ROLE_NAME,
            {},
            [],
            True,
            None,
            {
                "organization_membership": {},
                "team_membership": {"testorg": {"testteam": True}},
                'rbac_roles': {
                    'system': {'roles': {}},
                    'organizations': {'testorg': {'roles': {}, 'teams': {'testteam': {'roles': {TEAM_MEMBER_ROLE_NAME: True}}}}},
                },
            },
            [{1: True, 'enabled': True}],
            id=f"Assign {TEAM_MEMBER_ROLE_NAME} role to team 'testteam' using map_type 'role'",
        ),
        pytest.param(
            {"always": {}},
            "role",
            ORG_MEMBER_ROLE_NAME,  # Team removed from auth map in the test
            {},
            [],
            True,
            None,
            {
                "organization_membership": {"testorg": True},
                "team_membership": {},
                'rbac_roles': {'system': {'roles': {}}, 'organizations': {'testorg': {'roles': {ORG_MEMBER_ROLE_NAME: True}, 'teams': {}}}},
            },
            [{1: True, 'enabled': True}],
            id=f"Assign {ORG_MEMBER_ROLE_NAME} role to organization 'testorg' using map_type 'role'",
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
            [{1: True, 'enabled': True}],
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
            [{1: False, 'enabled': True}],
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
    org_member_rd,
    member_rd,
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
    if role == ORG_MEMBER_ROLE_NAME:
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

    if connection.vendor == 'postgresql' and local_authenticator_map.id != 1:
        # All of the test cases define exp_last_login_results with ID 1.
        # But if we are running in postgres we will get sequential IDs back.
        # So we need to massage the exp_last_login_results to have the correct ID
        exp_last_login_map_results[0][local_authenticator_map.id] = exp_last_login_map_results[0][1]
        del exp_last_login_map_results[0][1]

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
    logger.error.assert_called_once()
    f"Map type bad_map_type of rule {local_authenticator_map.name} does not know how to be processed" in logger.error.call_args


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

    with mock.patch(f"ansible_base.authentication.utils.claims.{process_function}", return_value=claims.TriggerResult.SKIP):
        res = claims.create_claims(authenticator, "username", {}, [])

    assert res["access_allowed"] is True
    assert res["is_superuser"] is granted
    assert res["claims"] == {"team_membership": {}, "organization_membership": {}, "rbac_roles": default_rbac_roles_claims}
    if revoke:
        assert res["last_login_map_results"] == [{local_authenticator_map.pk: False, 'enabled': True}]
    else:
        assert res["last_login_map_results"] == [{local_authenticator_map.pk: "skipped", 'enabled': True}]


@pytest.mark.parametrize(
    "trigger_condition, groups, has_access",
    [
        # has_or
        ({"has_or": ["foo"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_or": ["foo", "bar"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["bar"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["baz"], claims.TriggerResult.SKIP),
        ({"has_or": ["foo", "bar"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["foo", "baz"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["bar", "baz"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"]}, ["baz", "foo", "qux"], claims.TriggerResult.ALLOW),
        # has_and
        ({"has_and": ["foo"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_and": ["foo"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_and": ["foo", "bar"]}, ["bar", "foo"], claims.TriggerResult.ALLOW),
        ({"has_and": ["foo", "bar"]}, ["foo"], claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["baz"], claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["foo", "baz"], claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["bar", "baz"], claims.TriggerResult.SKIP),
        # has_not
        ({"has_not": ["foo"]}, ["foo"], claims.TriggerResult.SKIP),
        ({"has_not": ["foo"]}, ["bar"], claims.TriggerResult.ALLOW),
        ({"has_not": ["foo", "bar"]}, ["foo"], claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["baz"], claims.TriggerResult.ALLOW),
        ({"has_not": ["foo", "bar"]}, ["foo", "bar"], claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["foo", "baz"], claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["bar", "baz"], claims.TriggerResult.SKIP),
        ({"has_not": ["foo"]}, ["baz", "foo", "qux"], claims.TriggerResult.SKIP),
        # has_or and has_and (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "baz"], claims.TriggerResult.ALLOW),
        # has_or and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "baz"], claims.TriggerResult.ALLOW),
        # has_and and has_not (only has_and has effect)
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["baz", "foo"], claims.TriggerResult.ALLOW),
        # has_or, has_and, and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["bar"], claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["baz"], claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo", "baz"], claims.TriggerResult.ALLOW),
        # None of has_or, has_and, or has_not
        ({}, ["foo"], claims.TriggerResult.SKIP),
        ({"foo": "bar"}, ["foo"], claims.TriggerResult.SKIP),
        # Case insensitivity (always enabled)
        ({"has_or": ["FOO"]}, ["foo"], claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"]}, ["FOO"], claims.TriggerResult.ALLOW),
        ({"has_or": ["bAR"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_and": ["fOo", "bAr"]}, ["foo", "bar"], claims.TriggerResult.ALLOW),
        ({"has_not": ["FOO"]}, ["foo"], claims.TriggerResult.SKIP),
        ({"has_and": ["fOo", "bAr"]}, ["foo", "BaZ"], claims.TriggerResult.SKIP),
    ],
)
@pytest.mark.django_db
def test_process_groups(trigger_condition, groups, has_access):
    """
    Test the process_groups function.
    """
    res = claims.process_groups(trigger_condition, groups, map_id=1, tracking_id="xxx")
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
            claims.TriggerResult.ALLOW,
            id="equals, positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": "foo@example.org"},
            claims.TriggerResult.SKIP,
            id="equals, negative",
        ),
        pytest.param(
            {"email": {"matches": ".*@ex.*"}},
            {"email": "foo@example.com"},
            claims.TriggerResult.ALLOW,
            id="matches, positive",
        ),
        pytest.param(
            {"email": {"matches": "^foo@.*"}},
            {"email": "foo@example.com"},
            claims.TriggerResult.ALLOW,
            id="matches, start of line, positive",
        ),
        pytest.param(
            {"email": {"matches": "foo@.*"}},
            {"email": "bar@example.com"},
            claims.TriggerResult.SKIP,
            id="matches, negative",
        ),
        pytest.param(
            {"email": {"matches": "^foo@.*"}},
            {"email": "bar@example.com"},
            claims.TriggerResult.SKIP,
            id="matches, start of line, negative",
        ),
        pytest.param(
            {"email": {"contains": "@example.com"}},
            {"email": "foo@example.com"},
            claims.TriggerResult.ALLOW,
            id="contains, positive",
        ),
        pytest.param(
            {"email": {"contains": "@example.com"}},
            {"email": "foo@example.org"},
            claims.TriggerResult.SKIP,
            id="contains, negative",
        ),
        pytest.param(
            {"email": {"ends_with": "@example.com"}},
            {"email": "foo@example.com"},
            claims.TriggerResult.ALLOW,
            id="ends_with, positive",
        ),
        pytest.param(
            {"email": {"ends_with": "@example.com"}},
            {"email": "foo@example.org"},
            claims.TriggerResult.SKIP,
            id="ends_with, negative",
        ),
        pytest.param(
            {"email": {"in": ["foo@example.com", "bar@example.org"]}},
            {"email": "foo@example.com"},
            claims.TriggerResult.ALLOW,
            id="in, positive",
        ),
        pytest.param(
            {"email": {"in": ["foo@example.com", "bar@example.org"]}},
            {"email": "baz@example.net"},
            claims.TriggerResult.SKIP,
            id="in, negative",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "baz@example.net"},
            claims.TriggerResult.SKIP,
            id="'and' join_condition, missing one attribute, negative",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "baz@example.net", "favorite_color": "red"},
            claims.TriggerResult.SKIP,
            id="'and' join_condition, two false conditions, negative",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org", "favorite_color": "teal"},
            claims.TriggerResult.SKIP,
            id="'and' join_condition, one false condition, negative",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "join_condition": "and",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "teal"},
            claims.TriggerResult.ALLOW,
            id="'and' join_condition, positive",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "join_condition": "or",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "teal"},
            claims.TriggerResult.ALLOW,
            id="'or' join_condition, both conditions true, positive",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "join_condition": "or",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "red"},
            claims.TriggerResult.ALLOW,
            id="'or' join_condition, one condition true, positive",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.com", "favorite_color": "red"},
            claims.TriggerResult.ALLOW,
            id="implicit 'or' join_condition, one condition true, positive",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org", "favorite_color": "red"},
            claims.TriggerResult.SKIP,
            id="implicit 'or' join_condition, both conditions false, negative",
        ),
        pytest.param(
            {
                "email": {"in": ["foo@example.com", "bar@example.org"]},
                "join_condition": "or",
                "favorite_color": {
                    "equals": "teal",
                },
            },
            {"email": "foo@example.org", "favorite_color": "red"},
            claims.TriggerResult.SKIP,
            id="'or' join_condition, both conditions false, negative",
        ),
        pytest.param(
            {"email": {"invalid": "omg hey foo@example.com bye"}},
            {"email": "foo@example.org"},
            claims.TriggerResult.SKIP,
            id="invalid predicate in trigger conditions returns None",
        ),
        pytest.param(
            {"email": {}},
            {"email": "foo@example.org"},
            claims.TriggerResult.ALLOW,
            id="trigger dict attribute has empty dict, becomes 'exists', positive",
        ),
        pytest.param(
            {"email": {}},
            {"favorite_color": "teal"},
            claims.TriggerResult.SKIP,
            id="trigger dict attribute has empty dict, becomes 'exists', negative",
        ),
        pytest.param(
            {"email": {}},
            {},
            claims.TriggerResult.SKIP,
            id="trigger dict attribute has empty dict, becomes 'exists', empty attributes, negative",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}},
            {"favorite_color": "teal"},
            claims.TriggerResult.ALLOW,
            id="trigger dict attributes have empty dicts, becomes 'exists', implicit 'or', positive",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "or"},
            {"favorite_color": "teal"},
            claims.TriggerResult.ALLOW,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'or', positive",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "and"},
            {"favorite_color": "teal"},
            claims.TriggerResult.SKIP,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'and', negative",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "and"},
            {"favorite_color": "teal", "email": "foo@example.com"},
            claims.TriggerResult.ALLOW,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'and', positive",
        ),
        pytest.param(
            {"email": {"contains": "example"}},
            {"email": None},
            claims.TriggerResult.SKIP,
            id="user attribute is None, no predicate checks, returns None",
        ),
        pytest.param(
            {"email": {}},
            {"email": None},
            claims.TriggerResult.ALLOW,
            id="user attribute is None, exists check still works, negative",
        ),
        # It can take a list, and in that case the same join_condition works internally too
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": ["bar@example.com", "baz@example.com"]},
            claims.TriggerResult.SKIP,
            id="user attribute is list, no matches, negative",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": ["bar@example.com", "foo@example.com"]},
            claims.TriggerResult.ALLOW,
            id="user attribute is list, one match, implicit 'or', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": ["bar@example.com", "foo@example.com"]},
            claims.TriggerResult.SKIP,
            id="user attribute is list, one match, explicit 'and', negative",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": ["foo@example.com", "foo@example.com"]},
            claims.TriggerResult.ALLOW,
            id="user attribute is list, all matches, explicit 'and', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": ["foo@example.com", "foo@example.com"]},
            claims.TriggerResult.ALLOW,
            id="user attribute is list, all matches, explicit 'or', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": []},
            claims.TriggerResult.SKIP,
            id="user attribute is empty list, explicit 'and', returns None",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": []},
            claims.TriggerResult.SKIP,
            id="user attribute is empty list, explicit 'or', returns None",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": ["foo@example.com", "bar@example.com"]},
            claims.TriggerResult.ALLOW,
            id="user attribute is list, explicit 'or', second match is false, positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "invalid"},
            {"email": ["foo@example.com", "bar@example.com"]},
            claims.TriggerResult.ALLOW,
            id="join condition is invalid, defaults to or",
        ),
        pytest.param(
            {"username": {"equals": "alice"}, "join_condition": "or"},
            {"username": "bob", "email": ""},
            claims.TriggerResult.SKIP,
            id="user attribute is string, condition equals, join condition or, negative",
        ),
        # Case insensitivity (always enabled)
        pytest.param(
            {"username": {"equals": "lowercase"}, "join_condition": "or"},
            {"username": "LOWERCASE"},
            claims.TriggerResult.ALLOW,
            id="username attribute value case mismatch",
        ),
        pytest.param(
            {"uSeRnAmE": {"equals": "bbelcher"}, "join_condition": "or"},
            {"username": "bbelcher"},
            claims.TriggerResult.ALLOW,
            id="username attribute name/key case mismatch",
        ),
        pytest.param(
            {"USERNAME": {"equals": "lowercase"}, "join_condition": "or"},
            {"username": "LOWERCASE"},
            claims.TriggerResult.ALLOW,
            id="username attribute name/key and value case mismatch",
        ),
        pytest.param(
            {"username": {"contains": "USER"}, "join_condition": "or"},
            {"username": "myusername"},
            claims.TriggerResult.ALLOW,
            id="username attribute value case mismatch contains",
        ),
        pytest.param(
            {"username": {"in": ["BOB", "JOE", "JOHN", "TAMAR"]}, "join_condition": "or"},
            {"username": "tamar"},
            claims.TriggerResult.ALLOW,
            id="username attribute value case mismatch in",
        ),
        pytest.param(
            {"email": {"matches": ".*@REDHAT.COM"}, "join_condition": "or"},
            {"email": "fred@redhat.com"},
            claims.TriggerResult.ALLOW,
            id="email attribute value case mismatch matches",
        ),
        pytest.param(
            {"email": {}},
            {"email": None},
            claims.TriggerResult.ALLOW,
            id="user attribute is None, exists check still works",
        ),
        pytest.param(
            {"department": {"in": ["Engineering", "Sales", "Marketing"]}},
            {"department": "Engineering"},
            claims.TriggerResult.ALLOW,
            id="in operator with list value, positive match",
        ),
        pytest.param(
            {"department": {"in": ["Engineering", "Sales", "Marketing"]}},
            {"department": "HR"},
            claims.TriggerResult.SKIP,
            id="in operator with list value, negative match",
        ),
        pytest.param(
            {"department": {"in": ["Engineering", "Sales", "Marketing"]}},
            {"department": "engineering"},
            claims.TriggerResult.ALLOW,
            id="in operator with list value, case insensitive match",
        ),
        pytest.param(
            {"department": {"in": "Engineering"}},
            {"department": "Engineering"},
            claims.TriggerResult.SKIP,
            id="in operator with string value (invalid) should be ignored",
        ),
        pytest.param(
            {"cn": {"ends_with": "_admin"}, "employeeType": {"equals": "manager"}, "join_condition": "and"},
            {"cn": ["ldap_admin"]},
            claims.TriggerResult.SKIP,
            id="missing attribute required by 'and' condition should result in skip",
        ),
        pytest.param(
            {"cn": {"ends_with": "_admin"}, "employeeType": {"equals": "manager"}, "join_condition": "or"},
            {"cn": ["ldap_admin"]},
            claims.TriggerResult.ALLOW,
            id="missing attribute when using 'or' condition should result in allow",
        ),
        pytest.param(
            {"cn": {"ends_with": "_admin"}, "employeeType": {"equals": "manager"}, "join_condition": "and"},
            {"cn": ["ldap_org_admin"], "employeeType": ["manager"]},
            claims.TriggerResult.ALLOW,
            id="all attribute required by 'and' condition should result in allow",
        ),
    ],
)
@pytest.mark.django_db
def test_process_user_attributes(trigger_condition, attributes, expected):
    res = claims.process_user_attributes(trigger_condition, attributes, map_id=1, tracking_id="xxx")
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


def test_update_user_claims_attrs_override(user, local_authenticator_map):
    """
    Verify that when attrs is explicitly passed to update_user_claims, it is
    used for attribute-based trigger evaluation instead of extra_data.

    This simulates the OIDC pipeline flow where the identity provider's response
    contains claims (like preferred_username) that are NOT stored in extra_data
    but should still be available for authenticator map attribute matching.
    """
    local_authenticator_map.triggers = {"attributes": {"preferred_username": {"contains": "oidc_user"}}}
    local_authenticator_map.save()
    authenticator = local_authenticator_map.authenticator
    authenticator_user = AuthenticatorUser(
        provider=authenticator,
        user=user,
        extra_data={"id": "some-sub-value", "token_type": "Bearer"},
    )
    authenticator_user.save()

    # Without attrs override, the trigger won't match (preferred_username not in extra_data)
    result = claims.update_user_claims(user, authenticator, [])
    assert result is user  # still allowed (no "allow" map to block)

    # Verify the map didn't fire by checking that last_login_map_results shows "skipped"
    authenticator_user.refresh_from_db()
    map_results = authenticator_user.last_login_map_results
    assert map_results[0][str(local_authenticator_map.pk)] == "skipped"

    # With attrs override containing the claim, the trigger SHOULD match
    oidc_response = {"preferred_username": "oidc_user_1", "email": "user@example.com", "sub": "abc123"}
    result = claims.update_user_claims(user, authenticator, [], attrs=oidc_response)
    assert result is user

    authenticator_user.refresh_from_db()
    map_results = authenticator_user.last_login_map_results
    assert map_results[0][str(local_authenticator_map.pk)] is True


def test_update_user_claims_saml_attrs_override(user, local_authenticator_map):
    """
    Verify that SAML-style attrs (list values) are correctly matched by
    attribute-based triggers when passed via the attrs parameter.

    SAML identity providers return attribute values as lists
    (e.g., ["true"] instead of "true"). The trigger evaluator should handle
    both formats via _normalize_user_value().
    """
    local_authenticator_map.triggers = {"attributes": {"is_superuser": {"contains": "true"}}}
    local_authenticator_map.save()
    authenticator = local_authenticator_map.authenticator
    authenticator_user = AuthenticatorUser(
        provider=authenticator,
        user=user,
        extra_data={"id": "saml-uid", "token_type": "Bearer"},
    )
    authenticator_user.save()

    # SAML attrs have list values — this is what the pipeline now passes
    # after extracting response["attributes"]
    saml_attrs = {"is_superuser": ["true"], "email": ["user@example.com"]}
    result = claims.update_user_claims(user, authenticator, [], attrs=saml_attrs)
    assert result is user

    authenticator_user.refresh_from_db()
    map_results = authenticator_user.last_login_map_results
    assert map_results[0][str(local_authenticator_map.pk)] is True


@pytest.mark.parametrize("enabled", [True, False])
def test_create_claims_with_map_enabled_or_disabled(enabled, local_authenticator):
    # Create an AuthenticatorMap object with the parameterized "enabled" value
    AuthenticatorMap.objects.create(
        authenticator=local_authenticator,
        triggers={"always": {}},
        map_type="is_superuser",
        enabled=enabled,
    )

    result = claims.create_claims(local_authenticator, "testuser", {}, [])

    # Assert based on the "enabled" value
    if enabled:
        assert result["is_superuser"] is not None, "Claim should be present when enabled is True"
    else:
        assert result["is_superuser"] is None, "Claim should be None when enabled is False"


@pytest.mark.parametrize(
    "map_type,map_role,map_org,map_team,attributes,expected_value",
    [
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'Test',
            "{% for_attr_value(member_of) %}",
            {"member_of": "a"},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'Test': {
                            'roles': {},
                            'teams': {
                                'a': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'Test': {
                        'a': True,
                    },
                },
            },
            id="single_team_expansion_basic",
        ),
        # Parameterization after this created by AI
        pytest.param(
            'team',
            TEAM_ADMIN_ROLE_NAME,
            'Engineering',
            "{% for_attr_value(departments) %}",
            {"departments": ["frontend", "backend", "devops"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'Engineering': {
                            'roles': {},
                            'teams': {
                                'frontend': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'backend': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'devops': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'Engineering': {
                        'frontend': True,
                        'backend': True,
                        'devops': True,
                    },
                },
            },
            id="multiple_teams_expansion_from_list",
        ),
        pytest.param(
            'organization',
            ORG_ADMIN_ROLE_NAME,
            "{% for_attr_value(company_orgs) %}",
            None,
            {"company_orgs": ["Sales", "Marketing", "HR"]},
            {
                'organization_membership': {
                    'Sales': True,
                    'Marketing': True,
                    'HR': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Sales': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Marketing': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'HR': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="multiple_organizations_expansion",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            "{% for_attr_value(org_names) %}",
            "{% for_attr_value(team_names) %}",
            {"org_names": ["Org1", "Org2"], "team_names": ["TeamA", "TeamB"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'Org1': {
                            'roles': {},
                            'teams': {
                                'TeamA': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                'TeamB': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                        'Org2': {
                            'roles': {},
                            'teams': {
                                'TeamA': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                'TeamB': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'Org1': {
                        'TeamA': True,
                        'TeamB': True,
                    },
                    'Org2': {
                        'TeamA': True,
                        'TeamB': True,
                    },
                },
            },
            id="cartesian_product_org_team_expansion",
        ),
        pytest.param(
            'team',
            TEAM_ADMIN_ROLE_NAME,
            'Development',
            "{% for_attr_value(projects) %}",
            {"projects": "single_project"},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'Development': {
                            'roles': {},
                            'teams': {
                                'single_project': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'Development': {
                        'single_project': True,
                    },
                },
            },
            id="single_string_attribute_expansion",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'QA',
            "{% for_attr_value(missing_attr) %}",
            {"existing_attr": "value"},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="expansion_with_missing_attribute",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'Operations',
            "{% for_attr_value(empty_list) %}",
            {"empty_list": []},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="expansion_with_empty_list",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'Security',
            "{% for_attr_value(null_attr) %}",
            {"null_attr": None},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="expansion_with_null_attribute",
        ),
        pytest.param(
            'organization',
            ORG_MEMBER_ROLE_NAME,
            "{% for_attr_value(complex_orgs) %}",
            None,
            {"complex_orgs": ["Finance & Accounting", "R&D-Innovation", "Sales_North_America"]},
            {
                'organization_membership': {
                    'Finance & Accounting': True,
                    'R&D-Innovation': True,
                    'Sales_North_America': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Finance & Accounting': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'R&D-Innovation': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Sales_North_America': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="complex_organization_names_with_special_chars",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'Unicode-Org',
            "{% for_attr_value(unicode_teams) %}",
            {"unicode_teams": ["开发团队", "测试团队", "Équipe-FR"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'Unicode-Org': {
                            'roles': {},
                            'teams': {
                                '开发团队': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                '测试团队': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                'Équipe-FR': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'Unicode-Org': {
                        '开发团队': True,
                        '测试团队': True,
                        'Équipe-FR': True,
                    },
                },
            },
            id="unicode_team_names_expansion",
        ),
        pytest.param(
            'team',
            'Senior Developer',
            'Tech',
            "{% for_attr_value(nested_groups) %}",
            {"nested_groups": {"level1": ["web", "mobile"], "level2": ["api", "database"]}},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="expansion_with_nested_dict_attribute",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'BigOrg',
            "{% for_attr_value(large_team_list) %}",
            {"large_team_list": [f"team_{i:03d}" for i in range(1, 101)]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'BigOrg': {
                            'roles': {},
                            'teams': {
                                **{f"team_{i:03d}": {'roles': {TEAM_MEMBER_ROLE_NAME: True}} for i in range(1, 101)},
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'BigOrg': {
                        **{f"team_{i:03d}": True for i in range(1, 101)},
                    },
                },
            },
            id="large_scale_team_expansion",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'Mixed',
            "{% for_attr_value(mixed_types) %}",
            {"mixed_types": [1, "string", True, 3.14]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="mixed_data_types_in_expansion",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'TestOrg',
            "{% for_attr_value(duplicate_teams) %}",
            {"duplicate_teams": ["team1", "team2", "team1", "team3", "team2"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'TestOrg': {
                            'roles': {},
                            'teams': {
                                'team1': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                'team2': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                'team3': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'TestOrg': {
                        'team1': True,
                        'team2': True,
                        'team3': True,
                    },
                },
            },
            id="duplicate_values_in_expansion_list",
        ),
        pytest.param(
            'team',
            TEAM_MEMBER_ROLE_NAME,
            'DevOps',
            "{% for_attr_value(whitespace_teams) %}",
            {"whitespace_teams": [" team1 ", "team2\t", "\nteam3", "  team4  "]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'DevOps': {
                            'roles': {},
                            'teams': {
                                ' team1 ': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                'team2\t': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                '\nteam3': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                                '  team4  ': {
                                    'roles': {
                                        TEAM_MEMBER_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'DevOps': {
                        ' team1 ': True,
                        'team2\t': True,
                        '\nteam3': True,
                        '  team4  ': True,
                    },
                },
            },
            id="whitespace_handling_in_expansion",
        ),
        # Role map_type test cases
        pytest.param(
            'role',
            ORG_ADMIN_ROLE_NAME,
            'IT',
            'Infrastructure',
            {"user_roles": ["sysadmin", "dba", "network_admin"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'IT': {
                            'roles': {},
                            'teams': {
                                'Infrastructure': {
                                    'roles': {
                                        ORG_ADMIN_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'IT': {
                        'Infrastructure': True,
                    },
                },
            },
            id="role_map_type_basic_team_assignment",
        ),
        pytest.param(
            'role',
            SYSTEM_ROLE_NAME,
            'Business',
            None,
            {"management_roles": ["pm", "lead", "director"]},
            {
                'organization_membership': {
                    'Business': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Business': {
                            'roles': {
                                SYSTEM_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="role_map_type_organization_assignment",
        ),
        pytest.param(
            'role',
            SYSTEM_ROLE_NAME,
            None,
            None,
            {"admin_privileges": ["super_admin", "global_admin"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {
                            SYSTEM_ROLE_NAME: True,
                        },
                    },
                },
                'team_membership': {},
            },
            id="role_map_type_system_role_assignment",
        ),
        pytest.param(
            'role',
            TEAM_ADMIN_ROLE_NAME,
            "{% for_attr_value(departments) %}",
            "{% for_attr_value(teams) %}",
            {"departments": ["Engineering", "QA"], "teams": ["Backend", "Frontend"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'Engineering': {
                            'roles': {},
                            'teams': {
                                'Backend': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'Frontend': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                        'QA': {
                            'roles': {},
                            'teams': {
                                'Backend': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'Frontend': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'Engineering': {
                        'Backend': True,
                        'Frontend': True,
                    },
                    'QA': {
                        'Backend': True,
                        'Frontend': True,
                    },
                },
            },
            id="role_map_type_with_expansion_org_and_team",
        ),
        pytest.param(
            'role',
            ORG_MEMBER_ROLE_NAME,
            "{% for_attr_value(security_orgs) %}",
            None,
            {"security_orgs": ["Security", "Compliance", "Risk Management"]},
            {
                'organization_membership': {
                    'Security': True,
                    'Compliance': True,
                    'Risk Management': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Security': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Compliance': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Risk Management': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="role_map_type_multiple_org_expansion",
        ),
        pytest.param(
            'role',
            'Developer',
            'Tech',
            "{% for_attr_value(empty_teams) %}",
            {"empty_teams": []},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="role_map_type_empty_expansion",
        ),
        # Organization map_type test cases
        pytest.param(
            'organization',
            ORG_ADMIN_ROLE_NAME,
            'Corporate',
            None,
            {"corp_access": ["full", "admin"]},
            {
                'organization_membership': {
                    'Corporate': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Corporate': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_basic_assignment",
        ),
        pytest.param(
            'organization',
            ORG_MEMBER_ROLE_NAME,
            "{% for_attr_value(user_orgs) %}",
            None,
            {"user_orgs": ["Finance", "Legal", "HR", "Operations"]},
            {
                'organization_membership': {
                    'Finance': True,
                    'Legal': True,
                    'HR': True,
                    'Operations': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Finance': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Legal': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'HR': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Operations': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_multiple_org_expansion",
        ),
        pytest.param(
            'organization',
            ORG_ADMIN_ROLE_NAME,
            "{% for_attr_value(regional_orgs) %}",
            None,
            {"regional_orgs": ["North America", "Europe", "Asia-Pacific"]},
            {
                'organization_membership': {
                    'North America': True,
                    'Europe': True,
                    'Asia-Pacific': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'North America': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Europe': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Asia-Pacific': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_regional_expansion",
        ),
        pytest.param(
            'organization',
            ORG_MEMBER_ROLE_NAME,
            "{% for_attr_value(client_orgs) %}",
            None,
            {"client_orgs": ["Client-A Corp", "Client-B LLC", "Client-C Inc"]},
            {
                'organization_membership': {
                    'Client-A Corp': True,
                    'Client-B LLC': True,
                    'Client-C Inc': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Client-A Corp': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Client-B LLC': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Client-C Inc': {
                            'roles': {
                                ORG_MEMBER_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_client_orgs_expansion",
        ),
        pytest.param(
            'organization',
            'Organization Contributor',
            "{% for_attr_value(missing_orgs) %}",
            None,
            {"other_attr": "value"},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_missing_attribute",
        ),
        pytest.param(
            'organization',
            'Organization Analyst',
            "{% for_attr_value(null_orgs) %}",
            None,
            {"null_orgs": None},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {},
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_null_attribute",
        ),
        pytest.param(
            'organization',
            ORG_ADMIN_ROLE_NAME,
            "{% for_attr_value(single_org) %}",
            None,
            {"single_org": "Single Organization"},
            {
                'organization_membership': {
                    'Single Organization': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Single Organization': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_single_string_expansion",
        ),
        pytest.param(
            'organization',
            ORG_ADMIN_ROLE_NAME,
            "{% for_attr_value(special_char_orgs) %}",
            None,
            {"special_char_orgs": ["Org@123", "Org#456", "Org$789", "Org%ABC"]},
            {
                'organization_membership': {
                    'Org@123': True,
                    'Org#456': True,
                    'Org$789': True,
                    'Org%ABC': True,
                },
                'rbac_roles': {
                    'organizations': {
                        'Org@123': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Org#456': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Org$789': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                        'Org%ABC': {
                            'roles': {
                                ORG_ADMIN_ROLE_NAME: True,
                            },
                            'teams': {},
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_special_characters",
        ),
        # Mixed scenarios with different map_types
        pytest.param(
            'role',
            TEAM_ADMIN_ROLE_NAME,
            "{% for_attr_value(dynamic_orgs) %}",
            "{% for_attr_value(dynamic_teams) %}",
            {"dynamic_orgs": ["Alpha", "Beta"], "dynamic_teams": ["Team1", "Team2", "Team3"]},
            {
                'organization_membership': {},
                'rbac_roles': {
                    'organizations': {
                        'Alpha': {
                            'roles': {},
                            'teams': {
                                'Team1': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'Team2': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'Team3': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                        'Beta': {
                            'roles': {},
                            'teams': {
                                'Team1': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'Team2': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                                'Team3': {
                                    'roles': {
                                        TEAM_ADMIN_ROLE_NAME: True,
                                    },
                                },
                            },
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {
                    'Alpha': {
                        'Team1': True,
                        'Team2': True,
                        'Team3': True,
                    },
                    'Beta': {
                        'Team1': True,
                        'Team2': True,
                        'Team3': True,
                    },
                },
            },
            id="role_map_type_complex_cartesian_expansion",
        ),
        pytest.param(
            'organization',
            ORG_MEMBER_ROLE_NAME,
            "{% for_attr_value(managed_orgs) %}",
            None,
            {"managed_orgs": [f"Org-{i:02d}" for i in range(1, 26)]},
            {
                'organization_membership': {
                    **{f"Org-{i:02d}": True for i in range(1, 26)},
                },
                'rbac_roles': {
                    'organizations': {
                        **{
                            f"Org-{i:02d}": {
                                'roles': {
                                    ORG_MEMBER_ROLE_NAME: True,
                                },
                                'teams': {},
                            }
                            for i in range(1, 26)
                        },
                    },
                    'system': {
                        'roles': {},
                    },
                },
                'team_membership': {},
            },
            id="organization_map_type_large_scale_expansion",
        ),
    ],
)
def test_expansion_in_claims(
    local_authenticator_map,
    map_type,
    map_role,
    map_org,
    map_team,
    attributes,
    expected_value,
    org_admin_rd,
    org_member_rd,
    admin_rd,
    member_rd,
    system_role,
):
    """
    Test that we properly append to org_team_mapping
    """
    local_authenticator_map.triggers = {"always": {}}
    local_authenticator_map.organization = map_org
    local_authenticator_map.team = map_team
    local_authenticator_map.map_type = map_type
    local_authenticator_map.role = map_role
    local_authenticator_map.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, "username", attributes, [])

    assert res["claims"] == expected_value


# Unit tests for refactored helper functions
class TestClaimsHelperFunctions:
    """Test cases for the refactored helper functions in claims processing"""

    @pytest.mark.parametrize(
        "input_value, expected",
        [
            ("TestString", "teststring"),
            (["Test", "STRING", 123, None], ["test", "string", "123", "none"]),
            (123, 123),
            (None, None),
            ({"key": "value"}, {"key": "value"}),
        ],
    )
    def test_lowercase_value(self, input_value, expected):
        """Test _lowercase_value with various input types"""
        result = claims._lowercase_value(input_value)
        assert result == expected

    @pytest.mark.parametrize(
        "input_dict, expected",
        [
            ({}, {}),
            (
                {"equals": "TestValue", "in": ["Value1", "Value2"], "contains": "SUBSTRING", "numeric": 123},
                {"equals": "testvalue", "in": ["value1", "value2"], "contains": "substring", "numeric": 123},
            ),
        ],
    )
    def test_lowercase_dict(self, input_dict, expected):
        """Test _lowercase_dict with various dictionary inputs"""
        result = claims._lowercase_dict(input_dict)
        assert result == expected

    @pytest.mark.parametrize(
        "trigger_condition, expected",
        [
            ({"USERNAME": "TestUser", "Email": "TEST@EXAMPLE.COM"}, {"username": "testuser", "email": "test@example.com"}),
            (
                {"USERNAME": {"equals": "TestUser"}, "Department": {"in": ["Engineering", "Sales"]}, "Role": {}},
                {"username": {"equals": "testuser"}, "department": {"in": ["engineering", "sales"]}, "role": {}},
            ),
            (
                {"SimpleAttr": "Value", "ComplexAttr": {"contains": "SUBSTRING"}, "NumericAttr": 123, "join_condition": "and"},
                {"simpleattr": "value", "complexattr": {"contains": "substring"}, "numericattr": 123, "join_condition": "and"},
            ),
        ],
    )
    def test_lowercase_attr_triggers(self, trigger_condition, expected):
        """Test _lowercase_attr_triggers with various trigger condition types"""
        result = claims._lowercase_attr_triggers(trigger_condition)
        assert result == expected

    @pytest.mark.parametrize(
        "join_condition, expected",
        [
            ("or", "or"),
            ("and", "and"),
            ("invalid", "or"),
            ("OR", "or"),  # Should be invalid and default to 'or'
            ("", "or"),
            (None, "or"),
        ],
    )
    def test_validate_join_condition(self, join_condition, expected, caplog):
        """Test _validate_join_condition with various inputs"""
        result = claims._validate_join_condition(join_condition, 1, "test-id")
        assert result == expected

        if join_condition not in ["or", "and"]:
            assert "invalid and will be set to 'or'" in caplog.text

    @pytest.mark.parametrize(
        "condition, expected_result, expected_log_contains",
        [
            ({"equals": "value", "contains": "substring"}, True, None),
            ({"equals": "value", "invalid_op": "test"}, True, "invalid_op"),
            ({"in": "should_be_list"}, False, "must use an array"),
            ({"in": ["value1", "value2"]}, True, None),
        ],
    )
    def test_validate_attribute_conditions(self, condition, expected_result, expected_log_contains, caplog):
        """Test _validate_attribute_conditions with various condition types"""
        result = claims._validate_attribute_conditions("test_attr", condition, 1, "test-id")
        assert result is expected_result

        if expected_log_contains:
            assert expected_log_contains in caplog.text

    @pytest.mark.parametrize(
        "trigger_condition, attributes, expected_trigger, expected_attrs",
        [
            (
                {"USERNAME": {"equals": "TestUser"}},
                {"USERNAME": "TestUser"},
                {"username": {"equals": "testuser"}},
                {"username": "TestUser"},  # Keys lowercased, values unchanged
            ),
        ],
    )
    def test_prepare_case_insensitive_data(self, trigger_condition, attributes, expected_trigger, expected_attrs):
        """Test _prepare_case_insensitive_data always normalizes case"""
        result_trigger, result_attrs = claims._prepare_case_insensitive_data(trigger_condition, attributes, 1, "test-id")
        assert result_trigger == expected_trigger
        assert result_attrs == expected_attrs

    @pytest.mark.parametrize(
        "user_value, expected",
        [
            ("string_value", ["string_value"]),
            (["already", "a", "list"], ["already", "a", "list"]),
            (123, [123]),
            (None, [None]),
            ({"key": "value"}, [{"key": "value"}]),
        ],
    )
    def test_normalize_user_value(self, user_value, expected):
        """Test _normalize_user_value with various input types"""
        result = claims._normalize_user_value(user_value)
        assert result == expected
        assert isinstance(result, list)


class TestRoleUserAssignmentsCache:
    """Test cases for the RoleUserAssignmentsCache class, specifically the cache_existing method"""

    @pytest.fixture
    def cache_instance(self, db):
        """Create a fresh cache instance for each test"""
        return claims.RoleUserAssignmentsCache()

    @pytest.fixture
    def mock_role_definition(self):
        """Create a mock role definition"""
        role_def = mock.Mock()
        role_def.name = "Test Role"
        role_def.id = 1
        return role_def

    @pytest.fixture
    def mock_content_type(self):
        """Create a mock content type"""
        content_type = mock.Mock()
        content_type.id = 10
        return content_type

    @pytest.fixture
    def mock_content_object(self):
        """Create a mock content object (Organization or Team)"""
        content_obj = mock.Mock()
        content_obj.id = 100
        return content_obj

    def create_mock_role_assignment(
        self, role_definition=None, content_type_id=None, object_id=None, content_object=None, role_definition_id=None, content_type_service=None
    ):
        """Helper to create a mock role assignment"""
        from ansible_base.rbac.remote import get_local_resource_prefix

        assignment = mock.Mock()
        assignment.role_definition = role_definition
        assignment.content_type_id = content_type_id
        assignment.object_id = object_id
        assignment.content_object = content_object
        assignment.role_definition_id = role_definition_id or (role_definition.id if role_definition else 1)

        # Set up content_type mock for local role assignment filtering
        if content_type_id is None:
            assignment.content_type = None
        else:
            content_type_mock = mock.Mock()
            content_type_mock.service = content_type_service or get_local_resource_prefix()  # Default to local for caching
            assignment.content_type = content_type_mock

        return assignment

    @pytest.mark.parametrize(
        "content_type_id, object_id, expected_content_type_key, expected_object_key, should_have_content_object",
        [
            # System-wide role (None object_id)
            pytest.param(None, None, None, None, False, id="system_wide_role"),
            # Integer object_id
            pytest.param(10, 100, 10, 100, True, id="integer_object_id"),
            # String that converts to integer object_id
            pytest.param(10, "100", 10, 100, True, id="string_to_int_object_id"),
        ],
    )
    def test_cache_existing_with_valid_object_ids(
        self,
        cache_instance,
        mock_role_definition,
        mock_content_object,
        content_type_id,
        object_id,
        expected_content_type_key,
        expected_object_key,
        should_have_content_object,
    ):
        """Test caching role assignments with various valid object_id types"""

        assignment = self.create_mock_role_assignment(
            role_definition=mock_role_definition,
            content_type_id=content_type_id,
            object_id=object_id,
            content_object=mock_content_object if should_have_content_object else None,
        )

        cache_instance.cache_existing([assignment])

        # Verify cache structure
        assert "Test Role" in cache_instance.cache
        assert expected_content_type_key in cache_instance.cache["Test Role"]
        assert expected_object_key in cache_instance.cache["Test Role"][expected_content_type_key]

        cached_entry = cache_instance.cache["Test Role"][expected_content_type_key][expected_object_key]
        expected_object = mock_content_object if should_have_content_object else None
        assert cached_entry['object'] == expected_object
        assert cached_entry['status'] == cache_instance.STATUS_EXISTING

        # Verify role definition is cached
        assert "Test Role" in cache_instance.role_definitions
        assert cache_instance.role_definitions["Test Role"] == mock_role_definition

    @pytest.mark.parametrize(
        "object_id, expected_key, expected_log_message, should_be_cached",
        [
            # Valid string to int conversion
            pytest.param("123", 123, None, True, id="valid_string_to_int"),
            pytest.param("0", 0, None, True, id="zero_string_to_int"),
            pytest.param("-1", -1, None, True, id="negative_string_to_int"),
            # Invalid string conversion - not cached
            pytest.param("not-a-number", None, "Unable to cache object_id not-a-number: Could not cast to type int", False, id="invalid_string"),
            # Invalid object_id type - not cached
            pytest.param({'invalid': 'dict'}, None, "Unable to cache object_id", False, id="invalid_dict_type"),
            pytest.param([], None, "Unable to cache object_id", False, id="invalid_list_type"),
        ],
    )
    def test_cache_existing_with_object_id_conversion_and_errors(
        self, cache_instance, mock_role_definition, caplog, object_id, expected_key, expected_log_message, should_be_cached
    ):
        """Test caching role assignments with object_id conversion and error handling"""
        assignment = self.create_mock_role_assignment(role_definition=mock_role_definition, content_type_id=10, object_id=object_id, content_object=mock.Mock())

        cache_instance.cache_existing([assignment])

        # Verify logging if expected
        if expected_log_message:
            assert expected_log_message in caplog.text

        # Verify cache structure based on whether it should be cached
        if should_be_cached:
            cached_entry = cache_instance.cache["Test Role"][10][expected_key]
            assert cached_entry['object'] is not None
            assert cached_entry['status'] == cache_instance.STATUS_EXISTING
        else:
            # For error cases, nothing should be cached at the object_id level
            if "Test Role" in cache_instance.cache and 10 in cache_instance.cache["Test Role"]:
                # If the role exists, ensure the problematic object_id is not there
                assert expected_key not in cache_instance.cache["Test Role"][10]

    def test_cache_existing_multiple_assignments(self, cache_instance, mock_content_object):
        """Test caching multiple role assignments"""
        role_def1 = mock.Mock()
        role_def1.name = "Role 1"
        role_def1.id = 1

        role_def2 = mock.Mock()
        role_def2.name = "Role 2"
        role_def2.id = 2

        assignments = [
            self.create_mock_role_assignment(role_definition=role_def1, content_type_id=10, object_id=100, content_object=mock_content_object),
            self.create_mock_role_assignment(role_definition=role_def2, content_type_id=None, object_id=None, content_object=None),
            self.create_mock_role_assignment(role_definition=role_def1, content_type_id=20, object_id=200, content_object=mock.Mock()),
        ]

        cache_instance.cache_existing(assignments)

        # Verify all assignments are cached
        assert "Role 1" in cache_instance.cache
        assert "Role 2" in cache_instance.cache

        # Verify Role 1 has two entries (different content types)
        assert 10 in cache_instance.cache["Role 1"]
        assert 20 in cache_instance.cache["Role 1"]
        assert 100 in cache_instance.cache["Role 1"][10]
        assert 200 in cache_instance.cache["Role 1"][20]

        # Verify Role 2 has system-wide entry
        assert None in cache_instance.cache["Role 2"]
        assert None in cache_instance.cache["Role 2"][None]

        # Verify all role definitions are cached
        assert len(cache_instance.role_definitions) == 2
        assert cache_instance.role_definitions["Role 1"] == role_def1
        assert cache_instance.role_definitions["Role 2"] == role_def2

    def test_cache_existing_role_definition_already_cached(self, cache_instance, mock_role_definition):
        """Test that role definition is not overwritten if already cached"""
        # Pre-cache a role definition
        cache_instance.role_definitions["Test Role"] = mock_role_definition

        # Create assignment with different role definition object but same name
        different_role_def = mock.Mock()
        different_role_def.name = "Test Role"
        different_role_def.id = 1

        assignment = self.create_mock_role_assignment(role_definition=different_role_def, content_type_id=10, object_id=100, content_object=mock.Mock())

        # Mock _rd_by_id to return the pre-cached role definition
        with mock.patch.object(cache_instance, '_rd_by_id', return_value=mock_role_definition):
            cache_instance.cache_existing([assignment])

        # Verify original role definition is preserved
        assert cache_instance.role_definitions["Test Role"] == mock_role_definition

    def test_cache_existing_empty_list(self, cache_instance):
        """Test caching with empty list of assignments"""
        cache_instance.cache_existing([])

        # Cache should remain empty
        assert len(cache_instance.cache) == 0
        assert len(cache_instance.role_definitions) == 0

    def test_cache_existing_preserves_existing_cache(self, cache_instance, mock_role_definition, mock_content_object):
        """Test that existing cache entries are preserved when adding new ones"""
        # First, cache one assignment
        assignment1 = self.create_mock_role_assignment(
            role_definition=mock_role_definition, content_type_id=10, object_id=100, content_object=mock_content_object
        )
        cache_instance.cache_existing([assignment1])

        # Verify first assignment is cached
        assert cache_instance.cache["Test Role"][10][100]['status'] == cache_instance.STATUS_EXISTING

        # Now add another assignment
        role_def2 = mock.Mock()
        role_def2.name = "Another Role"
        role_def2.id = 2

        assignment2 = self.create_mock_role_assignment(role_definition=role_def2, content_type_id=20, object_id=200, content_object=mock.Mock())
        cache_instance.cache_existing([assignment2])

        # Verify both assignments are in cache
        assert "Test Role" in cache_instance.cache
        assert "Another Role" in cache_instance.cache
        assert cache_instance.cache["Test Role"][10][100]['status'] == cache_instance.STATUS_EXISTING
        assert cache_instance.cache["Another Role"][20][200]['status'] == cache_instance.STATUS_EXISTING


class TestRefactoredCacheExisting:
    """Test cases for the refactored cache_existing method and _cache_role_assignment helper"""

    @pytest.fixture
    def cache_instance(self, db):
        """Create a fresh cache instance for each test"""
        return claims.RoleUserAssignmentsCache()

    @pytest.fixture
    def mock_role_definition(self):
        """Create a mock role definition"""
        role_def = mock.Mock()
        role_def.name = "Test Role"
        role_def.id = 1
        return role_def

    def create_mock_role_assignment(self, role_definition=None, content_type_id=None, object_id=None, content_object=None, content_type_service=None):
        """Helper to create a mock role assignment"""
        from ansible_base.rbac.remote import get_local_resource_prefix

        assignment = mock.Mock()
        assignment.role_definition = role_definition
        assignment.content_type_id = content_type_id
        assignment.object_id = object_id
        assignment.content_object = content_object
        assignment.role_definition_id = role_definition.id if role_definition else 1

        # Set up content_type mock for service filtering
        if content_type_id is None:
            assignment.content_type = None
        else:
            content_type_mock = mock.Mock()
            content_type_mock.service = content_type_service or get_local_resource_prefix()
            assignment.content_type = content_type_mock

        return assignment

    @pytest.mark.parametrize(
        "content_type_id, object_id, service_type, should_be_cached, test_description",
        [
            pytest.param(None, None, None, True, "global role", id="global_role"),
            pytest.param(10, 100, "local", True, "local service role", id="local_service"),
            pytest.param(20, 200, "shared", True, "shared service role", id="shared_service"),
            pytest.param(30, 300, "remote-service", False, "remote service role", id="remote_service"),
            pytest.param(40, 400, "external-api", False, "external API service role", id="external_service"),
        ],
    )
    def test_cache_existing_with_service_filtering(
        self, cache_instance, mock_role_definition, content_type_id, object_id, service_type, should_be_cached, test_description
    ):
        """Test that cache_existing properly filters roles based on service type"""
        from ansible_base.rbac.remote import get_local_resource_prefix

        # Handle special case for local service
        if service_type == "local":
            service_type = get_local_resource_prefix()

        assignment = self.create_mock_role_assignment(
            role_definition=mock_role_definition,
            content_type_id=content_type_id,
            object_id=object_id,
            content_object=mock.Mock() if content_type_id is not None else None,
            content_type_service=service_type,
        )

        cache_instance.cache_existing([assignment])

        # Verify cache behavior based on expectation
        if should_be_cached:
            assert "Test Role" in cache_instance.cache
            assert content_type_id in cache_instance.cache["Test Role"]
            assert object_id in cache_instance.cache["Test Role"][content_type_id]

            cached_entry = cache_instance.cache["Test Role"][content_type_id][object_id]
            assert cached_entry['status'] == cache_instance.STATUS_EXISTING
            if content_type_id is None:
                assert cached_entry['object'] is None
            else:
                assert cached_entry['object'] is not None
        else:
            # For roles that shouldn't be cached, verify they're not in the cache
            if "Test Role" in cache_instance.cache:
                assert content_type_id not in cache_instance.cache["Test Role"]

    @pytest.mark.parametrize(
        "content_type_id, object_id, expected_content_type_key, expected_object_key, has_content_object, test_description",
        [
            pytest.param(None, None, None, None, False, "global role", id="global_role"),
            pytest.param(10, "100", 10, 100, True, "object role with string object_id", id="object_role_string_id"),
            pytest.param(20, 200, 20, 200, True, "object role with integer object_id", id="object_role_int_id"),
            pytest.param(30, None, 30, None, False, "object role with None object_id", id="object_role_none_id"),
        ],
    )
    def test_cache_role_assignment_valid_cases(
        self,
        cache_instance,
        mock_role_definition,
        content_type_id,
        object_id,
        expected_content_type_key,
        expected_object_key,
        has_content_object,
        test_description,
    ):
        """Test _cache_role_assignment with various valid role types"""
        content_object = mock.Mock() if has_content_object else None
        assignment = self.create_mock_role_assignment(
            role_definition=mock_role_definition, content_type_id=content_type_id, object_id=object_id, content_object=content_object
        )

        # Initialize cache key first (this is done by cache_existing)
        cache_instance._init_cache_key(mock_role_definition.name, content_type_id=content_type_id)

        cache_instance._cache_role_assignment(mock_role_definition, assignment)

        # Verify role is cached correctly
        assert "Test Role" in cache_instance.cache
        assert expected_content_type_key in cache_instance.cache["Test Role"]
        assert expected_object_key in cache_instance.cache["Test Role"][expected_content_type_key]

        cached_entry = cache_instance.cache["Test Role"][expected_content_type_key][expected_object_key]
        assert cached_entry['status'] == cache_instance.STATUS_EXISTING

        if has_content_object:
            assert cached_entry['object'] == content_object
        else:
            assert cached_entry['object'] is None

    @pytest.mark.parametrize(
        "invalid_object_id, expected_log_fragment",
        [
            pytest.param("invalid-id", "Unable to cache object_id invalid-id: Could not cast to type int", id="invalid_string"),
            pytest.param({"dict": "value"}, "Unable to cache object_id {'dict': 'value'}: Could not cast to type int", id="invalid_dict"),
            pytest.param(["list", "value"], "Unable to cache object_id ['list', 'value']: Could not cast to type int", id="invalid_list"),
            pytest.param("", "Unable to cache object_id : Could not cast to type int", id="empty_string"),
            pytest.param("12.34", "Unable to cache object_id 12.34: Could not cast to type int", id="float_string"),
        ],
    )
    def test_cache_role_assignment_object_id_conversion_error(self, cache_instance, mock_role_definition, caplog, invalid_object_id, expected_log_fragment):
        """Test _cache_role_assignment with various object_id conversion errors"""
        assignment = self.create_mock_role_assignment(
            role_definition=mock_role_definition, content_type_id=10, object_id=invalid_object_id, content_object=mock.Mock()
        )

        # Initialize cache key first (this is done by cache_existing)
        cache_instance._init_cache_key(mock_role_definition.name, content_type_id=10)

        cache_instance._cache_role_assignment(mock_role_definition, assignment)

        # Verify error is logged
        assert expected_log_fragment in caplog.text

        # Verify nothing is cached due to error
        if "Test Role" in cache_instance.cache and 10 in cache_instance.cache["Test Role"]:
            # The cache key structure exists but no object should be cached
            assert len(cache_instance.cache["Test Role"][10]) == 0

    @pytest.mark.parametrize(
        "assignments_config, expected_cached_content_types, expected_skipped_content_types",
        [
            pytest.param(
                [
                    {"content_type_id": 10, "object_id": 100, "service": "remote-service", "should_cache": False},
                    {"content_type_id": None, "object_id": None, "service": None, "should_cache": True},
                ],
                [None],  # Only global role should be cached
                [10],  # Remote service role should be skipped
                id="skip_remote_cache_global",
            ),
            pytest.param(
                [
                    {"content_type_id": 10, "object_id": 100, "service": "local", "should_cache": True},
                    {"content_type_id": 20, "object_id": 200, "service": "external", "should_cache": False},
                    {"content_type_id": 30, "object_id": 300, "service": "shared", "should_cache": True},
                ],
                [10, 30],  # Local and shared should be cached
                [20],  # External should be skipped
                id="mixed_services",
            ),
            pytest.param(
                [
                    {"content_type_id": 10, "object_id": 100, "service": "remote-1", "should_cache": False},
                    {"content_type_id": 20, "object_id": 200, "service": "remote-2", "should_cache": False},
                ],
                [],  # Nothing should be cached
                [10, 20],  # All remote services should be skipped
                id="all_remote_services",
            ),
        ],
    )
    def test_cache_existing_early_return_pattern(
        self, cache_instance, mock_role_definition, assignments_config, expected_cached_content_types, expected_skipped_content_types
    ):
        """Test that cache_existing uses early return pattern correctly with various service combinations"""
        from ansible_base.rbac.remote import get_local_resource_prefix

        assignments = []
        for config in assignments_config:
            service = config["service"]
            if service == "local":
                service = get_local_resource_prefix()

            assignment = self.create_mock_role_assignment(
                role_definition=mock_role_definition,
                content_type_id=config["content_type_id"],
                object_id=config["object_id"],
                content_object=mock.Mock() if config["content_type_id"] is not None else None,
                content_type_service=service,
            )
            assignments.append(assignment)

        cache_instance.cache_existing(assignments)

        # Verify expected cached content types
        if expected_cached_content_types:
            assert "Test Role" in cache_instance.cache
            for content_type_id in expected_cached_content_types:
                assert content_type_id in cache_instance.cache["Test Role"]
        else:
            # If nothing should be cached, the role might not even exist in cache
            if "Test Role" in cache_instance.cache:
                assert len(cache_instance.cache["Test Role"]) == 0

        # Verify expected skipped content types
        if "Test Role" in cache_instance.cache:
            for content_type_id in expected_skipped_content_types:
                assert content_type_id not in cache_instance.cache["Test Role"]


# --- AAP-45394 regression tests ---


@mock.patch("ansible_base.authentication.utils.claims.logger")
def test_create_claims_allow_grant_no_error_logged(
    logger,
    local_authenticator_map,
    shut_up_logging,
):
    """
    Regression test for AAP-45047: map_type 'allow' with a firing trigger
    must NOT log an error or fall through to the catch-all else branch.
    """
    local_authenticator_map.triggers = {"always": {}}
    local_authenticator_map.map_type = "allow"
    local_authenticator_map.save()

    authenticator = local_authenticator_map.authenticator
    claims.create_claims(authenticator, "username", {}, [])

    logger.error.assert_not_called()


def test_create_claims_deny_all_then_allow_override(
    local_authenticator_map,
    local_authenticator_map_1,
):
    """
    Regression test for AAP-45394: a deny-all allow map at order=1 must be
    recoverable by an allow-always allow map at order=2.

    Before the fix the 'allow' branch only triggered when has_permission=False,
    so the affirmative branch (has_permission=True) was silently dropped and
    access remained denied.
    """
    # order=1: deny-all rule (trigger 'never' -> has_permission=False)
    local_authenticator_map.map_type = 'allow'
    local_authenticator_map.triggers = {'never': {}}
    local_authenticator_map.order = 1
    local_authenticator_map.save()

    # order=2: allow-always rule (trigger 'always' -> has_permission=True)
    local_authenticator_map_1.map_type = 'allow'
    local_authenticator_map_1.triggers = {'always': {}}
    local_authenticator_map_1.order = 2
    local_authenticator_map_1.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, 'username', {}, [])

    assert res['access_allowed'] is True, 'An allow-always map at order=2 must override a deny-all map at order=1 (AAP-45394)'


def test_create_claims_deny_all_not_overridden_without_match(
    local_authenticator_map,
    local_authenticator_map_1,
):
    """
    Regression test for AAP-45394: when the user does NOT match the second
    allow map's trigger, access must remain denied.
    """
    # order=1: deny-all
    local_authenticator_map.map_type = 'allow'
    local_authenticator_map.triggers = {'never': {}}
    local_authenticator_map.order = 1
    local_authenticator_map.save()

    # order=2: allow only for members of group 'special-group'; user has no groups
    local_authenticator_map_1.map_type = 'allow'
    local_authenticator_map_1.triggers = {'groups': {'has_or': ['special-group']}}
    local_authenticator_map_1.order = 2
    local_authenticator_map_1.save()

    authenticator = local_authenticator_map.authenticator
    # Pass an empty groups list -- the user is NOT in 'special-group'
    res = claims.create_claims(authenticator, 'username', {}, [])

    assert res['access_allowed'] is False, 'User not matching the second allow map must remain denied (AAP-45394)'


def test_create_claims_deny_all_overridden_with_group_match(
    local_authenticator_map,
    local_authenticator_map_1,
):
    """
    Regression test for AAP-45394: when the user DOES match the second allow
    map's trigger, the deny from the first map must be overridden.
    """
    # order=1: deny-all
    local_authenticator_map.map_type = 'allow'
    local_authenticator_map.triggers = {'never': {}}
    local_authenticator_map.order = 1
    local_authenticator_map.save()

    # order=2: allow for members of 'special-group'
    local_authenticator_map_1.map_type = 'allow'
    local_authenticator_map_1.triggers = {'groups': {'has_or': ['special-group']}}
    local_authenticator_map_1.order = 2
    local_authenticator_map_1.save()

    authenticator = local_authenticator_map.authenticator
    # Pass 'special-group' in the groups list -- the user IS in the group
    res = claims.create_claims(authenticator, 'username', {}, ['special-group'])

    assert res['access_allowed'] is True, 'User matching the second allow map must have access granted despite earlier deny (AAP-45394)'


def test_create_claims_allow_then_deny_preserves_deny(
    local_authenticator_map,
    local_authenticator_map_1,
):
    """
    Verify the reverse ordering: allow-always at order=1, deny-all at order=2.
    The later deny must override the earlier allow (last writer wins).
    """
    local_authenticator_map.map_type = 'allow'
    local_authenticator_map.triggers = {'always': {}}
    local_authenticator_map.order = 1
    local_authenticator_map.save()

    local_authenticator_map_1.map_type = 'allow'
    local_authenticator_map_1.triggers = {'never': {}}
    local_authenticator_map_1.order = 2
    local_authenticator_map_1.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, 'username', {}, [])

    assert res['access_allowed'] is False, 'A deny-all map at order=2 must override an allow-always map at order=1'


def test_create_claims_revoke_deny_overridden_by_later_allow(
    local_authenticator_map,
    local_authenticator_map_1,
):
    """
    A revoke=True allow map whose trigger does not match converts SKIP to DENY.
    A subsequent allow-always map must override that denial (last writer wins).
    """
    # order=1: allow for group 'admins' with revoke=True
    # user NOT in admins -> SKIP -> revoke converts to DENY -> access_allowed=False
    local_authenticator_map.map_type = 'allow'
    local_authenticator_map.triggers = {'groups': {'has_or': ['admins']}}
    local_authenticator_map.revoke = True
    local_authenticator_map.order = 1
    local_authenticator_map.save()

    # order=2: allow-always -> access_allowed=True
    local_authenticator_map_1.map_type = 'allow'
    local_authenticator_map_1.triggers = {'always': {}}
    local_authenticator_map_1.order = 2
    local_authenticator_map_1.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, 'username', {}, [])

    assert res['access_allowed'] is True, 'An allow-always map must override a revoke-deny from an earlier map'


def test_create_claims_three_maps_last_writer_wins(
    local_authenticator_map,
    local_authenticator_map_1,
    local_authenticator_map_2,
):
    """
    Three allow maps: allow(1) -> deny(2) -> allow(3).
    The last evaluated map must win.
    """
    local_authenticator_map.map_type = 'allow'
    local_authenticator_map.triggers = {'always': {}}
    local_authenticator_map.order = 1
    local_authenticator_map.save()

    local_authenticator_map_1.map_type = 'allow'
    local_authenticator_map_1.triggers = {'never': {}}
    local_authenticator_map_1.order = 2
    local_authenticator_map_1.save()

    local_authenticator_map_2.map_type = 'allow'
    local_authenticator_map_2.triggers = {'always': {}}
    local_authenticator_map_2.order = 3
    local_authenticator_map_2.save()

    authenticator = local_authenticator_map.authenticator
    res = claims.create_claims(authenticator, 'username', {}, [])

    assert res['access_allowed'] is True, 'The last allow map (order=3, always) must win over the deny at order=2'


# ---------------------------------------------------------------------------
# Performance and correctness tests for optimized claims processing
# ---------------------------------------------------------------------------

# Deterministically-generated group names for performance tests.
# 33 groups matches the scale observed in production SAML responses.
_MANY_GROUPS = [f"group-{hashlib.sha256(f'seed-{i}'.encode()).hexdigest()[:16]}" for i in range(33)]
# Pick one to use as a known-present value in match tests
_KNOWN_GROUP = _MANY_GROUPS[7]


class TestProcessUserValueInOperatorLogVolume:
    """Verify the 'in' operator emits O(1) log lines per evaluation, not O(n) per user value."""

    def test_in_operator_emits_one_log_line_per_map(self, caplog):
        """The 'in' operator must emit at most 1 log line per map, not per value."""
        tc = {'groups': {'in': ['nonexistent_group']}}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            claims._process_user_value(None, tc, _MANY_GROUPS, 'or', 'groups', 1, 'log-test')

        attr_log_lines = [r for r in caplog.records if 'groups' in r.getMessage() and 'Map [1]' in r.getMessage()]
        assert len(attr_log_lines) == 1, (
            f"Expected 1 summary log line for 'in' operator, got {len(attr_log_lines)}: " f"{[r.getMessage() for r in attr_log_lines]}"
        )


class TestProcessUserValueInOperatorCorrectness:
    """Verify set-based 'in' operator produces identical results to per-value iteration."""

    def test_in_single_value_positive(self):
        tc = {'email': {'in': ['foo@example.com', 'bar@example.org']}}
        result = claims._process_user_value(None, tc, ['foo@example.com'], 'or', 'email', 1, 't')
        assert result is True

    def test_in_single_value_negative(self):
        tc = {'email': {'in': ['foo@example.com', 'bar@example.org']}}
        result = claims._process_user_value(None, tc, ['baz@example.net'], 'or', 'email', 1, 't')
        assert result is False

    def test_in_multi_value_any_match_or_join(self):
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(None, tc, ['user', 'admin', 'staff'], 'or', 'groups', 1, 't')
        assert result is True

    def test_in_multi_value_no_match_or_join(self):
        tc = {'groups': {'in': ['superadmin']}}
        result = claims._process_user_value(None, tc, ['user', 'admin', 'staff'], 'or', 'groups', 1, 't')
        assert result is False

    def test_in_multi_value_all_match_and_join(self):
        tc = {'groups': {'in': ['admin', 'user', 'staff']}}
        result = claims._process_user_value(None, tc, ['user', 'admin'], 'and', 'groups', 1, 't')
        assert result is True

    def test_in_multi_value_partial_match_and_join(self):
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(None, tc, ['user', 'admin'], 'and', 'groups', 1, 't')
        assert result is False

    def test_in_empty_user_value_returns_none(self):
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(None, tc, [], 'or', 'groups', 1, 't')
        assert result is None

    def test_in_case_insensitive(self):
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(None, tc, ['ADMIN'], 'or', 'groups', 1, 't')
        assert result is True

    def test_in_preserves_existing_has_access_true_or(self):
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(True, tc, ['nobody'], 'or', 'groups', 1, 't')
        assert result is True

    def test_in_flips_false_to_true_on_match_or(self):
        """has_access=False must flip to True when a match is found with 'or' join."""
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(False, tc, ['admin'], 'or', 'groups', 1, 't')
        assert result is True

    def test_in_preserves_false_on_no_match_or(self):
        """has_access=False stays False when no match is found with 'or' join."""
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(False, tc, ['nobody'], 'or', 'groups', 1, 't')
        assert result is False

    def test_in_preserves_existing_has_access_and(self):
        tc = {'groups': {'in': ['admin']}}
        result = claims._process_user_value(True, tc, ['nobody'], 'and', 'groups', 1, 't')
        assert result is False

    def test_in_case_insensitive_trigger_and_user(self):
        """Trigger values and user values with mixed case must match."""
        tc = {'groups': {'in': ['HybRid_Cloud_Admin']}}
        result = claims._process_user_value(None, tc, ['HYBRID_CLOUD_ADMIN'], 'or', 'groups', 1, 't')
        assert result is True

    def test_in_partial_match_and_join(self):
        """With 'and' join, partial match (some values in trigger) must return False."""
        tc = {'groups': {'in': ['admin', 'editor']}}
        result = claims._process_user_value(None, tc, ['admin', 'viewer'], 'and', 'groups', 1, 't')
        assert result is False

    def test_in_many_groups_single_trigger_no_match(self):
        """33 user groups, trigger has 1 non-matching value."""
        tc = {'groups': {'in': ['nonexistent_group']}}
        result = claims._process_user_value(None, tc, _MANY_GROUPS, 'or', 'groups', 1, 't')
        assert result is False

    def test_in_many_groups_single_trigger_with_match(self):
        """33 user groups, trigger has 1 matching value."""
        tc = {'groups': {'in': [_KNOWN_GROUP]}}
        result = claims._process_user_value(None, tc, _MANY_GROUPS, 'or', 'groups', 1, 't')
        assert result is True


class TestEarlyExitForOtherOperators:
    """Verify early exit for equals/contains/ends_with/matches operators."""

    def test_equals_early_exit_or_join(self, caplog):
        """With 'or' join, first match should stop iteration."""
        values = ['a', 'b', 'target', 'd', 'e']
        tc = {'attr': {'equals': 'target'}}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, values, 'or', 'attr', 1, 'exit-test')

        assert result is True
        value_logs = [r for r in caplog.records if 'value [' in r.getMessage() and 'Map [1]' in r.getMessage()]
        # Should have logged a, b, target — then stopped (3 not 5)
        assert len(value_logs) == 3, f"Expected early exit after 3 values, got {len(value_logs)} log lines"

    def test_equals_early_exit_and_join(self, caplog):
        """With 'and' join, first mismatch should stop iteration."""
        values = ['target', 'wrong', 'target', 'target']
        tc = {'attr': {'equals': 'target'}}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, values, 'and', 'attr', 1, 'exit-test')

        assert result is False
        value_logs = [r for r in caplog.records if 'value [' in r.getMessage() and 'Map [1]' in r.getMessage()]
        assert len(value_logs) == 2, f"Expected early exit after 2 values, got {len(value_logs)} log lines"

    def test_contains_early_exit_or_join(self, caplog):
        """With 'or' join, first match should stop iteration."""
        values = ['foo', 'bar', 'hello_world', 'baz']
        tc = {'attr': {'contains': 'world'}}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, values, 'or', 'attr', 1, 'exit-test')

        assert result is True
        value_logs = [r for r in caplog.records if 'value [' in r.getMessage() and 'Map [1]' in r.getMessage()]
        assert len(value_logs) == 3, f"Expected early exit after 3 values, got {len(value_logs)} log lines"

    def test_ends_with_early_exit_or_join(self, caplog):
        """With 'or' join, first match should stop iteration."""
        values = ['user@other.com', 'user@example.com', 'user@third.com']
        tc = {'attr': {'ends_with': '@example.com'}}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, values, 'or', 'attr', 1, 'exit-test')

        assert result is True
        value_logs = [r for r in caplog.records if 'value [' in r.getMessage() and 'Map [1]' in r.getMessage()]
        assert len(value_logs) == 2, f"Expected early exit after 2 values, got {len(value_logs)} log lines"

    def test_matches_early_exit_or_join(self, caplog):
        """With 'or' join, first regex match should stop iteration."""
        values = ['nope', 'admin-group-1', 'other']
        tc = {'attr': {'matches': r'^admin-.*'}}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, values, 'or', 'attr', 1, 'exit-test')

        assert result is True
        value_logs = [r for r in caplog.records if 'value [' in r.getMessage() and 'Map [1]' in r.getMessage()]
        assert len(value_logs) == 2, f"Expected early exit after 2 values, got {len(value_logs)} log lines"

    def test_matches_early_exit_and_join(self, caplog):
        """With 'and' join, first regex mismatch should stop iteration."""
        values = ['admin-1', 'not-admin', 'admin-2']
        tc = {'attr': {'matches': r'^admin-.*'}}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, values, 'and', 'attr', 1, 'exit-test')

        assert result is False
        value_logs = [r for r in caplog.records if 'value [' in r.getMessage() and 'Map [1]' in r.getMessage()]
        assert len(value_logs) == 2, f"Expected early exit after 2 values, got {len(value_logs)} log lines"


class TestProcessUserValueEdgeCases:
    """Cover branch conditions in _process_user_value for unknown operators and disabled logging."""

    def test_unknown_operator_returns_has_access_unchanged(self):
        """An unrecognized operator key should return has_access unchanged."""
        tc = {'attr': {'unknown_op': 'value'}}
        result = claims._process_user_value(None, tc, ['x'], 'or', 'attr', 1, 't')
        assert result is None

    def test_in_operator_with_logging_disabled(self, caplog):
        """The 'in' path must work correctly even when DEBUG logging is disabled."""
        tc = {'groups': {'in': ['admin']}}
        with caplog.at_level(logging.WARNING, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, ['admin'], 'or', 'groups', 1, 't')
        assert result is True
        attr_logs = [r for r in caplog.records if 'groups' in r.getMessage()]
        assert len(attr_logs) == 0

    def test_scalar_operator_with_logging_disabled(self, caplog):
        """Scalar operators must work correctly even when DEBUG logging is disabled."""
        tc = {'attr': {'equals': 'target'}}
        with caplog.at_level(logging.WARNING, logger='ansible_base.authentication.utils.claims'):
            result = claims._process_user_value(None, tc, ['target'], 'or', 'attr', 1, 't')
        assert result is True
        attr_logs = [r for r in caplog.records if 'attr' in r.getMessage().lower()]
        assert len(attr_logs) == 0


class TestProcessUserAttributesLogVolume:
    """End-to-end log volume test via the public process_user_attributes API."""

    def test_many_groups_attribute_in_operator_debug_log_volume(self, caplog):
        """342 evaluations must produce O(342) log lines, not O(342 * 33)."""
        trigger = {'groups': {'in': ['nonexistent']}}
        attrs = {'groups': _MANY_GROUPS}

        with caplog.at_level(logging.DEBUG, logger='ansible_base.authentication.utils.claims'):
            for _ in range(342):
                claims.process_user_attributes(dict(trigger), dict(attrs), map_id=1, tracking_id='vol')

        attr_lines = [r for r in caplog.records if 'groups' in r.getMessage().lower()]
        # 342 maps x 1 summary line = 342, not 342 x 33 = 11286
        assert len(attr_lines) <= 342, (
            f"Expected <= 342 attr log lines, got {len(attr_lines)}. " f"The 'in' operator should emit 1 summary line per evaluation, not per user value."
        )


@pytest.mark.django_db
class TestCreateClaimsQueryCount:
    """Integration test: create_claims must not issue N+1 queries."""

    def test_many_maps_query_count(self, local_authenticator, django_assert_num_queries):
        """create_claims must not issue N+1 queries for N maps."""
        for i in range(10):
            AuthenticatorMap.objects.create(
                name=f'map-{i}',
                authenticator=local_authenticator,
                map_type='allow',
                triggers={'attributes': {'email': {'in': ['test@example.com']}}},
                order=i,
            )

        with django_assert_num_queries(1):
            claims.create_claims(local_authenticator, 'testuser', {'email': 'test@example.com'}, [])
