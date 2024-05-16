import random
import string
from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from ansible_base.authentication.utils.claims import ReconcileUser, create_organizations_and_teams
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition

Organization = get_organization_model()
Team = get_team_model()
User = get_user_model()


def random_name(length: int = 10) -> str:
    return ''.join(random.choices(string.ascii_lowercase, k=length))


# NOTE(cutwater): Thiese fixtures partially duplicate ones defined in test_app/tests/rbac/conftest.py
#   We should unify this in future refactoring iterations.
@pytest.fixture(autouse=True)
def org_member_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'member_organization'],
        name=ReconcileUser.ORGANIZATION_MEMBER_ROLE_NAME,
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        managed=True,
    )


@pytest.fixture(autouse=True)
def team_member_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_team', 'member_team'],
        name=ReconcileUser.TEAM_MEMBER_ROLE_NAME,
        content_type=permission_registry.content_type_model.objects.get_for_model(Team),
        managed=True,
    )


@pytest.mark.django_db
def test_create_organizations_and_teams():
    results = {
        'claims': {
            'organization_membership': {'foo-org': True, 'foo-org-two': False},
            'team_membership': {'foo-org': {'foo-team': True, 'foo-team-two': False}},
        }
    }

    create_organizations_and_teams(results)

    assert Organization.objects.filter(name='foo-org').exists()
    assert not Organization.objects.filter(name='foo-org-two').exists()

    org = Organization.objects.get(name='foo-org')
    assert Team.objects.filter(name='foo-team', organization=org).exists()
    assert not Team.objects.filter(name='foo-team-two', organization=org).exists()


@pytest.mark.django_db
def test_add_user_to_org():
    org = Organization.objects.create(name='test-org-01')
    user = User.objects.create(username='test-user-01')

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False
    authenticator_user.claims = {
        'organization_membership': {'test-org-01': True, 'nonexist-org-01': True},
        'team_membership': {},
    }

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert user.has_obj_perm(org, 'member')


@pytest.mark.django_db
def test_add_user_to_team():
    org = Organization.objects.create(name='test-org-02')
    team = Team.objects.create(name='test-team-02', organization=org)
    user = User.objects.create(username='test-user-02')

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False
    authenticator_user.claims = {
        'organization_membership': {},
        'team_membership': {
            'test-org-02': {'test-team-02': True, 'nonexist-team-01': True},
            'nonexist-org': {'nonexist-team-02': True},
        },
    }

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert user.has_obj_perm(team, 'member')


@pytest.mark.django_db
def test_remove_user_from_org(org_member_rd):
    org = Organization.objects.create(name='test-org-01')
    user = User.objects.create(username='test-user-01')
    org_member_rd.give_permission(user, org)

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False
    authenticator_user.claims = {
        'organization_membership': {'test-org-01': False},
        'team_membership': {},
    }

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert not user.has_obj_perm(org, 'member')


@pytest.mark.django_db
def test_remove_user_from_team(team_member_rd):
    org = Organization.objects.create(name='test-org-02')
    team = Team.objects.create(name='test-team-02', organization=org)
    user = User.objects.create(username='test-user-02')
    team_member_rd.give_permission(user, team)

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False
    authenticator_user.claims = {
        'organization_membership': {},
        'team_membership': {'test-org-02': {'test-team-02': False}},
    }

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert not user.has_obj_perm(team, 'member')


@pytest.mark.django_db
@pytest.mark.parametrize('remove_users', [True, False])
def test_remove_users_setting_set(remove_users, org_member_rd, team_member_rd):
    org = Organization.objects.create(name='test-org')
    external_org = Organization.objects.create(name='test-ext-org')

    team = Team.objects.create(name='test-team', organization=org)
    external_team = Team.objects.create(name='test-ext-team', organization=external_org)

    user = User.objects.create(username='test-user')

    org_member_rd.give_permission(user, external_org)
    team_member_rd.give_permission(user, external_team)

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = remove_users
    authenticator_user.claims = {
        'organization_membership': {'test-org': True},
        'team_membership': {'test-org': {'test-team': True}},
    }

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert user.has_obj_perm(org, 'member')
    assert user.has_obj_perm(team, 'member')

    expect_has_perm = not remove_users
    assert user.has_obj_perm(external_org, 'member') == expect_has_perm
    assert user.has_obj_perm(external_org, 'member') == expect_has_perm
