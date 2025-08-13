from unittest import mock

import pytest
from django.conf import settings
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
    "trigger_condition, groups, case_insensitive, has_access",
    [
        # has_or
        ({"has_or": ["foo"]}, ["foo"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["foo", "bar"]}, ["foo"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["bar"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["baz"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["foo", "bar"]}, ["foo", "bar"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["foo", "baz"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo", "bar"]}, ["bar", "baz"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"]}, ["baz", "foo", "qux"], False, claims.TriggerResult.ALLOW),
        # has_and
        ({"has_and": ["foo"]}, ["foo"], False, claims.TriggerResult.ALLOW),
        ({"has_and": ["foo"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["foo", "bar"], False, claims.TriggerResult.ALLOW),
        ({"has_and": ["foo", "bar"]}, ["bar", "foo"], False, claims.TriggerResult.ALLOW),
        ({"has_and": ["foo", "bar"]}, ["foo"], False, claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["baz"], False, claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["foo", "baz"], False, claims.TriggerResult.SKIP),
        ({"has_and": ["foo", "bar"]}, ["bar", "baz"], False, claims.TriggerResult.SKIP),
        # has_not
        ({"has_not": ["foo"]}, ["foo"], False, claims.TriggerResult.SKIP),
        ({"has_not": ["foo"]}, ["bar"], False, claims.TriggerResult.ALLOW),
        ({"has_not": ["foo", "bar"]}, ["foo"], False, claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["baz"], False, claims.TriggerResult.ALLOW),
        ({"has_not": ["foo", "bar"]}, ["foo", "bar"], False, claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["foo", "baz"], False, claims.TriggerResult.SKIP),
        ({"has_not": ["foo", "bar"]}, ["bar", "baz"], False, claims.TriggerResult.SKIP),
        ({"has_not": ["foo"]}, ["baz", "foo", "qux"], False, claims.TriggerResult.SKIP),
        # has_or and has_and (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "bar"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"]}, ["foo", "baz"], False, claims.TriggerResult.ALLOW),
        # has_or and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_not": ["bar"]}, ["foo", "baz"], False, claims.TriggerResult.ALLOW),
        # has_and and has_not (only has_and has effect)
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo"], False, claims.TriggerResult.ALLOW),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["foo", "bar"], False, claims.TriggerResult.ALLOW),
        ({"has_and": ["foo"], "has_not": ["bar"]}, ["baz", "foo"], False, claims.TriggerResult.ALLOW),
        # has_or, has_and, and has_not (only has_or has effect)
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["bar"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["baz"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo", "bar"], False, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"], "has_and": ["bar"], "has_not": ["baz"]}, ["foo", "baz"], False, claims.TriggerResult.ALLOW),
        # None of has_or, has_and, or has_not
        ({}, ["foo"], False, claims.TriggerResult.SKIP),
        ({"foo": "bar"}, ["foo"], False, claims.TriggerResult.SKIP),
        # Case insensitivity (with and without flag enabled)
        ({"has_or": ["FOO"]}, ["foo"], True, claims.TriggerResult.ALLOW),
        ({"has_or": ["FOO"]}, ["foo"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["foo"]}, ["FOO"], True, claims.TriggerResult.ALLOW),
        ({"has_or": ["foo"]}, ["FOO"], False, claims.TriggerResult.SKIP),
        ({"has_or": ["bAR"]}, ["foo", "bar"], True, claims.TriggerResult.ALLOW),
        ({"has_or": ["bAR"]}, ["foo", "bar"], False, claims.TriggerResult.SKIP),
        ({"has_and": ["fOo", "bAr"]}, ["foo", "bar"], True, claims.TriggerResult.ALLOW),
        ({"has_and": ["fOo", "bAr"]}, ["foo", "bar"], False, claims.TriggerResult.SKIP),
        ({"has_not": ["FOO"]}, ["foo"], True, claims.TriggerResult.SKIP),
        ({"has_and": ["fOo", "bAr"]}, ["foo", "BaZ"], True, claims.TriggerResult.SKIP),
    ],
)
@pytest.mark.django_db
def test_process_groups(trigger_condition, groups, case_insensitive, has_access, settings_override_mutable):
    """
    Test the process_groups function.
    """
    with settings_override_mutable("FLAGS"):
        settings.FLAGS["FEATURE_CASE_INSENSITIVE_AUTH_MAPS"][0]["value"] = case_insensitive
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
    "trigger_condition, attributes, case_insensitive, expected",
    [
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": "foo@example.com"},
            False,
            claims.TriggerResult.ALLOW,
            id="equals, positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": "foo@example.org"},
            False,
            claims.TriggerResult.SKIP,
            id="equals, negative",
        ),
        pytest.param(
            {"email": {"matches": ".*@ex.*"}},
            {"email": "foo@example.com"},
            False,
            claims.TriggerResult.ALLOW,
            id="matches, positive",
        ),
        pytest.param(
            {"email": {"matches": "^foo@.*"}},
            {"email": "foo@example.com"},
            False,
            claims.TriggerResult.ALLOW,
            id="matches, start of line, positive",
        ),
        pytest.param(
            {"email": {"matches": "foo@.*"}},
            {"email": "bar@example.com"},
            False,
            claims.TriggerResult.SKIP,
            id="matches, negative",
        ),
        pytest.param(
            {"email": {"matches": "^foo@.*"}},
            {"email": "bar@example.com"},
            False,
            claims.TriggerResult.SKIP,
            id="matches, start of line, negative",
        ),
        pytest.param(
            {"email": {"contains": "@example.com"}},
            {"email": "foo@example.com"},
            False,
            claims.TriggerResult.ALLOW,
            id="contains, positive",
        ),
        pytest.param(
            {"email": {"contains": "@example.com"}},
            {"email": "foo@example.org"},
            False,
            claims.TriggerResult.SKIP,
            id="contains, negative",
        ),
        pytest.param(
            {"email": {"ends_with": "@example.com"}},
            {"email": "foo@example.com"},
            False,
            claims.TriggerResult.ALLOW,
            id="ends_with, positive",
        ),
        pytest.param(
            {"email": {"ends_with": "@example.com"}},
            {"email": "foo@example.org"},
            False,
            claims.TriggerResult.SKIP,
            id="ends_with, negative",
        ),
        pytest.param(
            {"email": {"in": "omg hey foo@example.com bye"}},
            {"email": "foo@example.com"},
            False,
            claims.TriggerResult.ALLOW,
            id="in, positive",
        ),
        pytest.param(
            {"email": {"in": "omg hey foo@example.com bye"}},
            {"email": "foo@example.org"},
            False,
            claims.TriggerResult.SKIP,
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
            claims.TriggerResult.SKIP,
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
            claims.TriggerResult.SKIP,
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
            claims.TriggerResult.SKIP,
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
            False,
            claims.TriggerResult.ALLOW,
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
            False,
            claims.TriggerResult.ALLOW,
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
            False,
            claims.TriggerResult.ALLOW,
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
            False,
            claims.TriggerResult.ALLOW,
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
            claims.TriggerResult.SKIP,
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
            claims.TriggerResult.SKIP,
            id="'or' join_condition, both conditions false, negative",
        ),
        pytest.param(
            {"email": {"invalid": "omg hey foo@example.com bye"}},
            {"email": "foo@example.org"},
            False,
            claims.TriggerResult.SKIP,
            id="invalid predicate in trigger conditions returns None",
        ),
        pytest.param(
            {"email": {}},
            {"email": "foo@example.org"},
            False,
            claims.TriggerResult.ALLOW,
            id="trigger dict attribute has empty dict, becomes 'exists', positive",
        ),
        pytest.param(
            {"email": {}},
            {"favorite_color": "teal"},
            False,
            claims.TriggerResult.SKIP,
            id="trigger dict attribute has empty dict, becomes 'exists', negative",
        ),
        pytest.param(
            {"email": {}},
            {},
            False,
            claims.TriggerResult.SKIP,
            id="trigger dict attribute has empty dict, becomes 'exists', empty attributes, negative",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}},
            {"favorite_color": "teal"},
            False,
            claims.TriggerResult.ALLOW,
            id="trigger dict attributes have empty dicts, becomes 'exists', implicit 'or', positive",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "or"},
            {"favorite_color": "teal"},
            False,
            claims.TriggerResult.ALLOW,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'or', positive",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "and"},
            {"favorite_color": "teal"},
            False,
            claims.TriggerResult.SKIP,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'and', negative",
        ),
        pytest.param(
            {"email": {}, "favorite_color": {}, "join_condition": "and"},
            {"favorite_color": "teal", "email": "foo@example.com"},
            False,
            claims.TriggerResult.ALLOW,
            id="trigger dict attributes have empty dicts, becomes 'exists', explicit 'and', positive",
        ),
        pytest.param(
            {"email": {"contains": "example"}},
            {"email": None},
            False,
            claims.TriggerResult.SKIP,
            id="user attribute is None, no predicate checks, returns None",
        ),
        pytest.param(
            {"email": {}},
            {"email": None},
            False,
            claims.TriggerResult.ALLOW,
            id="user attribute is None, exists check still works, negative",
        ),
        # It can take a list, and in that case the same join_condition works internally too
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": ["bar@example.com", "baz@example.com"]},
            False,
            claims.TriggerResult.SKIP,
            id="user attribute is list, no matches, negative",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}},
            {"email": ["bar@example.com", "foo@example.com"]},
            False,
            claims.TriggerResult.ALLOW,
            id="user attribute is list, one match, implicit 'or', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": ["bar@example.com", "foo@example.com"]},
            False,
            claims.TriggerResult.SKIP,
            id="user attribute is list, one match, explicit 'and', negative",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": ["foo@example.com", "foo@example.com"]},
            False,
            claims.TriggerResult.ALLOW,
            id="user attribute is list, all matches, explicit 'and', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": ["foo@example.com", "foo@example.com"]},
            False,
            claims.TriggerResult.ALLOW,
            id="user attribute is list, all matches, explicit 'or', positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "and"},
            {"email": []},
            False,
            claims.TriggerResult.SKIP,
            id="user attribute is empty list, explicit 'and', returns None",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": []},
            False,
            claims.TriggerResult.SKIP,
            id="user attribute is empty list, explicit 'or', returns None",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "or"},
            {"email": ["foo@example.com", "bar@example.com"]},
            False,
            claims.TriggerResult.ALLOW,
            id="user attribute is list, explicit 'or', second match is false, positive",
        ),
        pytest.param(
            {"email": {"equals": "foo@example.com"}, "join_condition": "invalid"},
            {"email": ["foo@example.com", "bar@example.com"]},
            False,
            claims.TriggerResult.ALLOW,
            id="join condition is invalid, defaults to or",
        ),
        pytest.param(
            {"username": {"equals": "alice"}, "join_condition": "or"},
            {"username": "bob", "email": ""},
            False,
            claims.TriggerResult.SKIP,
            id="user attribute is string, condition equals, join condition or, negative",
        ),
        pytest.param(
            {"username": {"equals": "lowercase"}, "join_condition": "or"},
            {"username": "LOWERCASE"},
            True,
            claims.TriggerResult.ALLOW,
            id="username attribute value case mismatch",
        ),
        pytest.param(
            {"username": {"equals": "lowercase"}, "join_condition": "or"},
            {"username": "LOWERCASE"},
            False,
            claims.TriggerResult.SKIP,
            id="username attribute value case mismatch",
        ),
        pytest.param(
            {"uSeRnAmE": {"equals": "bbelcher"}, "join_condition": "or"},
            {"username": "bbelcher"},
            True,
            claims.TriggerResult.ALLOW,
            id="username attribute name/key case mismatch",
        ),
        pytest.param(
            {"uSeRnAmE": {"equals": "bbelcher"}, "join_condition": "or"},
            {"username": "bbelcher"},
            False,
            claims.TriggerResult.SKIP,
            id="username attribute name/key case mismatch",
        ),
        pytest.param(
            {"USERNAME": {"equals": "lowercase"}, "join_condition": "or"},
            {"username": "LOWERCASE"},
            True,
            claims.TriggerResult.ALLOW,
            id="username attribute name/key and value case mismatch",
        ),
        pytest.param(
            {"username": {"contains": "USER"}, "join_condition": "or"},
            {"username": "myusername"},
            True,
            claims.TriggerResult.ALLOW,
            id="username attribute value case mismatch contains",
        ),
        pytest.param(
            {"username": {"in": "BOB JOE JOHN TAMAR"}, "join_condition": "or"},
            {"username": "tamar"},
            True,
            claims.TriggerResult.ALLOW,
            id="username attribute value case mismatch in",
        ),
        pytest.param(
            {"email": {"matches": ".*@REDHAT.COM"}, "join_condition": "or"},
            {"email": "fred@redhat.com"},
            True,
            claims.TriggerResult.ALLOW,
            id="email attribute value case mismatch matches",
        ),
        pytest.param(
            {"email": {}},
            {"email": None},
            True,
            claims.TriggerResult.ALLOW,
            id="user attribute is None, exists check still works, case sensitive, negative",
        ),
    ],
)
@pytest.mark.django_db
def test_process_user_attributes(trigger_condition, attributes, expected, case_insensitive, settings_override_mutable):
    with settings_override_mutable("FLAGS"):
        settings.FLAGS["FEATURE_CASE_INSENSITIVE_AUTH_MAPS"][0]["value"] = case_insensitive
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
