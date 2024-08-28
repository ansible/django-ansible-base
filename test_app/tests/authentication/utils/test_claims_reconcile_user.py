import random
import string
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from ansible_base.authentication.utils.claims import ReconcileUser, create_organizations_and_teams
from ansible_base.lib.utils.auth import get_organization_model, get_team_model

Organization = get_organization_model()
Team = get_team_model()
User = get_user_model()


def random_name(length: int = 10) -> str:
    return ''.join(random.choices(string.ascii_lowercase, k=length))


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
def test_add_user_to_org(org_member_rd, org_admin_rd, default_rbac_roles_claims):
    org = Organization.objects.create(name='test-org-01')
    org2 = Organization.objects.create(name='test-org-02')
    user = User.objects.create(username='test-user-01')

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False

    default_rbac_roles_claims['organizations'][org.name] = {'roles': {org_member_rd.name: True}, 'teams': {}}
    default_rbac_roles_claims['organizations'][org2.name] = {'roles': {org_admin_rd.name: True}, 'teams': {}}
    authenticator_user.claims = {'rbac_roles': default_rbac_roles_claims}

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert user.has_obj_perm(org, 'member')
    assert not user.has_obj_perm(org, 'change')
    assert user.has_obj_perm(org2, 'member')
    assert user.has_obj_perm(org2, 'change')


@pytest.mark.django_db
def test_add_user_to_team(member_rd, admin_rd, default_rbac_roles_claims):
    org = Organization.objects.create(name='test-org-01')
    org2 = Organization.objects.create(name='test-org-02')
    team = Team.objects.create(name='test-team-01', organization=org)
    team2 = Team.objects.create(name='test-team-02', organization=org)
    team3 = Team.objects.create(name='test-team-03', organization=org2)
    team4 = Team.objects.create(name='test-team-04', organization=org2)
    user = User.objects.create(username='test-user-02')

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False

    org_team_claims = {team.name: {'roles': {member_rd.name: True}}, team2.name: {'roles': {admin_rd.name: True}}}
    org2_team_claims = {team3.name: {'roles': {member_rd.name: True, admin_rd.name: True}}, team4.name: {'roles': {}}}

    default_rbac_roles_claims['organizations'][org.name] = {'roles': {}, 'teams': org_team_claims}
    default_rbac_roles_claims['organizations'][org2.name] = {'roles': {}, 'teams': org2_team_claims}

    authenticator_user.claims = {'rbac_roles': default_rbac_roles_claims}

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert not user.has_obj_perm(org, 'member')
    assert not user.has_obj_perm(org, 'change')

    assert user.has_obj_perm(team, 'member')
    assert not user.has_obj_perm(team, 'change')

    assert user.has_obj_perm(team2, 'member')
    assert user.has_obj_perm(team2, 'change')

    assert user.has_obj_perm(team3, 'member')
    assert user.has_obj_perm(team3, 'change')

    assert not user.has_obj_perm(team4, 'member')
    assert not user.has_obj_perm(team4, 'change')


@pytest.mark.django_db
def test_remove_user_from_org(org_member_rd, org_admin_rd, default_rbac_roles_claims):
    org = Organization.objects.create(name='test-org-01')
    org2 = Organization.objects.create(name='test-org-02')
    org3 = Organization.objects.create(name='test-org-03')
    user = User.objects.create(username='test-user-01')
    org_member_rd.give_permission(user, org)
    org_admin_rd.give_permission(user, org2)

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False

    default_rbac_roles_claims['organizations'][org.name] = {'roles': {org_member_rd.name: False}, 'teams': {}}
    default_rbac_roles_claims['organizations'][org2.name] = {'roles': {org_admin_rd.name: False}, 'teams': {}}
    default_rbac_roles_claims['organizations'][org3.name] = {'roles': {org_member_rd.name: False, org_admin_rd.name: False}, 'teams': {}}

    authenticator_user.claims = {'rbac_roles': default_rbac_roles_claims}

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert not user.has_obj_perm(org, 'member')
    assert not user.has_obj_perm(org2, 'change')
    assert not user.has_obj_perm(org3, 'member')
    assert not user.has_obj_perm(org3, 'change')


@pytest.mark.django_db
def test_remove_user_from_team(member_rd, admin_rd, default_rbac_roles_claims):
    org = Organization.objects.create(name='test-org-01')
    org2 = Organization.objects.create(name='test-org-02')
    team = Team.objects.create(name='test-team-01', organization=org)
    team2 = Team.objects.create(name='test-team-02', organization=org)
    team3 = Team.objects.create(name='test-team-03', organization=org2)
    team4 = Team.objects.create(name='test-team-04', organization=org)
    user = User.objects.create(username='test-user-01')

    member_rd.give_permission(user, team)
    admin_rd.give_permission(user, team2)
    member_rd.give_permission(user, team3)
    admin_rd.give_permission(user, team3)
    member_rd.give_permission(user, team4)

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False

    org_team_claims = {team.name: {'roles': {member_rd.name: False}}, team2.name: {'roles': {admin_rd.name: False}}}
    org2_team_claims = {team3.name: {'roles': {admin_rd.name: False}}, team4.name: {'roles': {}}}

    default_rbac_roles_claims['organizations'][org.name] = {'roles': {}, 'teams': org_team_claims}
    default_rbac_roles_claims['organizations'][org2.name] = {'roles': {}, 'teams': org2_team_claims}

    authenticator_user.claims = {'rbac_roles': default_rbac_roles_claims}

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert not user.has_obj_perm(team, 'member')
    assert not user.has_obj_perm(team2, 'change')
    assert user.has_obj_perm(team3, 'member')
    assert not user.has_obj_perm(team3, 'change')
    assert user.has_obj_perm(team4, 'member')


@pytest.mark.django_db
def test_add_user_to_global_role(global_role, global_role_1):
    user = User.objects.create(username='test-user')

    global_role.give_global_permission(user)

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False

    rbac_roles_claims = {'system': {'roles': {global_role.name: True, global_role_1.name: True}}, 'organizations': {}}
    authenticator_user.claims = {'rbac_roles': rbac_roles_claims}

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert user.role_assignments.filter(role_definition_id=global_role.id).exists()
    assert user.role_assignments.filter(role_definition_id=global_role_1.id).exists()


@pytest.mark.django_db
def test_remove_user_from_global_role(global_role, global_role_1):
    user = User.objects.create(username='test-user')

    global_role.give_global_permission(user)
    global_role_1.give_global_permission(user)

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = False

    rbac_roles_claims = {'system': {'roles': {global_role.name: False}}, 'organizations': {}}
    authenticator_user.claims = {'rbac_roles': rbac_roles_claims}

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    assert not user.role_assignments.filter(role_definition_id=global_role.id).exists()
    assert user.role_assignments.filter(role_definition_id=global_role_1.id).exists()


@pytest.mark.django_db
def test_remove_users_setting_set(org_member_rd, org_admin_rd, member_rd, admin_rd, global_role, global_role_1, global_role_2):
    """All roles not specified in claims are deleted with remove_users = True"""
    user = User.objects.create(username='test-user')

    global_role.give_global_permission(user)
    global_role_1.give_global_permission(user)
    global_role_2.give_global_permission(user)

    orgs, teams = [], []
    for i in range(3):
        orgs.append(Organization.objects.create(name=f'test-org-{i}'))
        org_member_rd.give_permission(user, orgs[i])
        org_admin_rd.give_permission(user, orgs[i])

        teams.append(Team.objects.create(name=f'test-team-{i}', organization=orgs[i]))
        member_rd.give_permission(user, teams[i])
        admin_rd.give_permission(user, teams[i])

    authenticator_user = mock.Mock()
    authenticator_user.provider.remove_users = True

    rbac_roles_claims = {
        'system': {'roles': {global_role.name: True, global_role_1.name: False}},
        'organizations': {
            orgs[0].name: {
                'roles': {org_member_rd.name: True},
                'teams': {
                    teams[0].name: {
                        'roles': {member_rd.name: True},
                    }
                },
            },
            orgs[1].name: {'roles': {org_member_rd.name: False}, 'teams': {teams[1].name: {'roles': {member_rd.name: False, admin_rd.name: True}}}},
            orgs[2].name: {'roles': {}, 'teams': {}},
        },
    }

    authenticator_user.claims = {'rbac_roles': rbac_roles_claims}

    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    # Only global_role was kept
    assert user.role_assignments.filter(content_type_id__isnull=True).count() == 1
    assert user.role_assignments.filter(role_definition_id=global_role.id).exists()

    # Org admin was not specified in orgs[0]
    assert user.has_obj_perm(orgs[0], 'member')
    assert not user.has_obj_perm(orgs[0], 'change')

    # Team admin was not specified in teams[0]
    assert user.has_obj_perm(teams[0], 'member')
    assert not user.has_obj_perm(teams[0], 'change')

    # All roles were either removed or not specified in orgs[1]
    assert not user.has_obj_perm(orgs[1], 'member')
    assert not user.has_obj_perm(orgs[1], 'change')

    # Only team admin was kept in teams[1]
    assert not user.role_assignments.filter(role_definition_id=member_rd.id, object_id=str(teams[1].id)).exists()
    assert user.has_obj_perm(teams[1], 'change')

    # Nothing was specified in orgs[2], teams[2]
    org_content_type = ContentType.objects.get_for_model(Organization)
    user_role_assignments_for_org_2 = user.role_assignments.filter(content_type=org_content_type, object_id=str(orgs[2].id))
    assert (
        not user_role_assignments_for_org_2.exists()
    ), f"Expected no assignments for org2 but got {', '.join([r.role_definition.name for r in user_role_assignments_for_org_2])}"
    team_content_type = ContentType.objects.get_for_model(Team)
    assert not user.role_assignments.filter(content_type=team_content_type, object_id=str(teams[2].id)).exists()
