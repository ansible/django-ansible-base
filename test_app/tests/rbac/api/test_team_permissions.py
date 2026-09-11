import pytest
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleTeamAssignment
from test_app.models import Organization, Team


@pytest.mark.django_db
class TestTeamListView:
    def test_team_list_superuser(self, admin_api_client, team):
        url = get_relative_url('team-list')
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1

    @pytest.mark.parametrize('admin_setting', [True, False])
    def test_org_admin_team_visibility_setting(self, user, user_api_client, organization, org_admin_rd, admin_setting):
        org_admin_rd.give_permission(user, organization)

        other_org = Organization.objects.create(name='other-org')
        Team.objects.create(name='team-in-own-org', organization=organization)
        Team.objects.create(name='team-in-other-org', organization=other_org)

        url = get_relative_url('team-list')
        with override_settings(ORG_ADMINS_CAN_SEE_ALL_TEAMS=admin_setting):
            response = user_api_client.get(url)

        assert response.status_code == 200
        team_names = {item['name'] for item in response.data['results']}

        if admin_setting:
            assert 'team-in-other-org' in team_names
        else:
            assert 'team-in-other-org' not in team_names

        assert 'team-in-own-org' in team_names

    def test_team_list_non_admin(self, user_api_client, team):
        url = get_relative_url('team-list')
        response = user_api_client.get(url)
        assert response.status_code == 200
        # user has no org membership — cannot see any teams
        assert team.name not in set(item['name'] for item in response.data['results'])

    def test_org_members_can_view_teams(self, user, user_api_client, organization, org_member_rd):
        own_team = Team.objects.create(name='team-in-own-org', organization=organization)
        other_org = Organization.objects.create(name='other-org')
        other_team = Team.objects.create(name='team-in-other-org', organization=other_org)

        url = get_relative_url('team-list')

        # Before any org membership, user sees neither team
        response = user_api_client.get(url)
        assert response.status_code == 200
        team_names = {item['name'] for item in response.data['results']}
        assert own_team.name not in team_names
        assert other_team.name not in team_names

        # After becoming an org member, user sees teams in their own org only
        org_member_rd.give_permission(user, organization)
        response = user_api_client.get(url)
        assert response.status_code == 200
        team_names = {item['name'] for item in response.data['results']}
        assert own_team.name in team_names
        assert other_team.name not in team_names

        # Org members cannot create teams
        response = user_api_client.post(url, data={'name': 'new-team', 'organization': organization.id})
        assert response.status_code == 403


@pytest.mark.django_db
class TestCrossOrgTeamRoleAssignment:
    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER=True, ORG_ADMINS_CAN_SEE_ALL_TEAMS=True)
    def test_org_admin_can_assign_org_role_to_cross_org_team(self, user, user_api_client, organization, org_admin_rd, org_member_rd):
        """Regression test for AAP-83161: org admin should be able to assign an
        org-level role to a team from another org when ORG_ADMINS_CAN_SEE_ALL_TEAMS=True."""
        org_a = organization
        org_b = Organization.objects.create(name='org-b')

        org_admin_rd.give_permission(user, org_a)
        team_b = Team.objects.create(name='team-in-org-b', organization=org_b)

        url = get_relative_url('roleteamassignment-list')
        data = {'role_definition': org_member_rd.id, 'object_id': org_a.id, 'team': team_b.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert RoleTeamAssignment.objects.filter(team=team_b, object_id=org_a.id).exists()

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER=True, ORG_ADMINS_CAN_SEE_ALL_TEAMS=False)
    def test_org_admin_cannot_assign_org_role_to_cross_org_team_when_setting_disabled(self, user, user_api_client, organization, org_admin_rd, org_member_rd):
        """When ORG_ADMINS_CAN_SEE_ALL_TEAMS=False the cross-org team is not visible,
        so the assignment request should fail with 400."""
        org_a = organization
        org_b = Organization.objects.create(name='org-b')

        org_admin_rd.give_permission(user, org_a)
        team_b = Team.objects.create(name='team-in-org-b', organization=org_b)

        url = get_relative_url('roleteamassignment-list')
        data = {'role_definition': org_member_rd.id, 'object_id': org_a.id, 'team': team_b.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        assert 'object does not exist' in response.data['team'][0]

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER=True, ORG_ADMINS_CAN_SEE_ALL_TEAMS=True)
    def test_org_admin_can_assign_org_role_to_own_org_team(self, user, user_api_client, organization, org_admin_rd, org_member_rd):
        """Baseline: org admins can still assign org-level roles to teams in their own org."""
        org_admin_rd.give_permission(user, organization)
        own_team = Team.objects.create(name='team-in-own-org', organization=organization)

        url = get_relative_url('roleteamassignment-list')
        data = {'role_definition': org_member_rd.id, 'object_id': organization.id, 'team': own_team.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert RoleTeamAssignment.objects.filter(team=own_team, object_id=organization.id).exists()

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER=True, ORG_ADMINS_CAN_SEE_ALL_TEAMS=True)
    def test_non_admin_cannot_assign_org_role_to_cross_org_team(self, user, user_api_client, organization, org_member_rd):
        """A plain org member lacks change permission on the org — assignment is blocked (403).
        The cross-org team IS visible (setting enabled + membership in org_b), but the
        permission check on the target org prevents the assignment."""
        org_b = Organization.objects.create(name='org-b')
        team_b = Team.objects.create(name='team-in-org-b', organization=org_b)

        org_member_rd.give_permission(user, organization)
        org_member_rd.give_permission(user, org_b)  # make team_b visible

        url = get_relative_url('roleteamassignment-list')
        data = {'role_definition': org_member_rd.id, 'object_id': organization.id, 'team': team_b.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 403, response.data

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER=True, ORG_ADMINS_CAN_SEE_ALL_TEAMS=True)
    def test_superuser_can_always_assign_org_role_to_cross_org_team(self, admin_api_client, organization, org_member_rd):
        """Superusers are never filtered by ORG_ADMINS_CAN_SEE_ALL_TEAMS and can assign
        org-level roles to teams from any organization."""
        org_b = Organization.objects.create(name='org-b')
        team_b = Team.objects.create(name='team-in-org-b', organization=org_b)

        url = get_relative_url('roleteamassignment-list')
        data = {'role_definition': org_member_rd.id, 'object_id': organization.id, 'team': team_b.id}

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert RoleTeamAssignment.objects.filter(team=team_b, object_id=organization.id).exists()

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER=True, ORG_ADMINS_CAN_SEE_ALL_TEAMS=True)
    def test_org_admin_escalation_flow(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        """Mirrors test_org_admins_can_add_members: demonstrates the full escalation path.

        An org admin of org_b (but not org_a) cannot assign cross-org team roles on org_a (403).
        After being elevated to org admin on org_a the same request succeeds (201), and
        atomicity of the first failure is confirmed by verifying no assignment was created."""
        org_b = Organization.objects.create(name='org-b')
        team_b = Team.objects.create(name='team-in-org-b', organization=org_b)

        # Give org admin on org_b so user can see team_b via ORG_ADMINS_CAN_SEE_ALL_TEAMS.
        # Give org member on org_a so the object_id lookup succeeds, but without the
        # change permission that org_admin_rd would grant.
        org_admin_rd.give_permission(user, org_b)
        org_member_rd.give_permission(user, organization)

        url = get_relative_url('roleteamassignment-list')
        data = {'role_definition': org_member_rd.id, 'object_id': organization.id, 'team': team_b.id}

        # Step 1: user can see org_a but is not its admin — cannot assign roles on it
        response = user_api_client.post(url, data=data)
        assert response.status_code == 403, response.data
        assert not RoleTeamAssignment.objects.filter(team=team_b, object_id=organization.id).exists()

        # Step 2: grant org admin on org_a — now the assignment succeeds
        org_admin_rd.give_permission(user, organization)
        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert RoleTeamAssignment.objects.filter(team=team_b, object_id=organization.id).exists()
