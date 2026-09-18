import pytest
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, RoleDefinition
from test_app.models import Organization, Team, User


@pytest.mark.django_db
class TestUserListView:
    CREATE_DATA = {'username': 'created-user', 'email': 'foo@foo.invalid', 'password': '$$$@@AAzzzz'}

    def test_user_list_superuser(self, admin_api_client, rando):
        url = get_relative_url('user-list')
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 2  # Count needs to be fixed due to duplicated user issue

        response = admin_api_client.post(url, data=self.CREATE_DATA)
        assert response.status_code == 201
        assert User.objects.filter(username='created-user').exists()

    def test_org_admin_can_create_user(self, user, user_api_client, organization, org_admin_rd):
        url = get_relative_url('user-list')
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1

        # user has no organization permissions at this point, can not create new user
        response = user_api_client.post(url, data=self.CREATE_DATA)
        assert response.status_code == 403
        assert not User.objects.filter(username='created-user').exists()

        # with the organization admin permission, user can create a new user
        org_admin_rd.give_permission(user, organization)
        response = user_api_client.post(url, data=self.CREATE_DATA)
        assert response.status_code == 201
        assert User.objects.filter(username='created-user').exists()

    def test_superuser_create_permission(self, user, user_api_client, organization, org_admin_rd):
        "Only superusers can create other superusers"
        url = get_relative_url('user-list')
        create_data = self.CREATE_DATA.copy()
        create_data['is_superuser'] = True

        # Ordinary users can not create superusers
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 403

        # Organization admins can not create superusers
        org_admin_rd.give_permission(user, organization)
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 403

        # Only other superusers can create a superuser
        user.is_superuser = True
        user.save(update_fields=['is_superuser'])
        response = user_api_client.post(url, data=create_data)
        assert response.status_code == 201
        assert User.objects.filter(username='created-user').exists()

    @pytest.mark.parametrize('admin_setting', [True, False])
    def test_org_admin_setting(self, user, user_api_client, org_admin_rd, organization, admin_setting):
        org_admin_rd.give_permission(user, organization)
        User.objects.create(username='rando')  # not in organization
        url = get_relative_url('user-list')
        with override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=admin_setting):
            response = user_api_client.get(url)
            response_usernames = set(item['username'] for item in response.data['results'])
        if admin_setting:
            assert 'rando' in response_usernames
        else:
            assert 'rando' not in response_usernames

    def test_org_members_can_view_users(self, user, user_api_client, organization, org_member_rd):
        rando = User.objects.create(username='rando')
        admin = User.objects.create(username='an-admin', is_superuser=True)
        url = get_relative_url('user-list')

        org_member_rd.give_permission(rando, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        response_users = set(item['id'] for item in response.data['results'])
        # User unassociated with organization can see themself and admin users
        assert not {user.id, admin.id} - response_users
        assert rando.id not in response_users

        org_member_rd.give_permission(user, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        response_users = set(item['id'] for item in response.data['results'])
        # Organization members can see other users in their organization
        assert not {user.id, rando.id, admin.id} - response_users

        # An organization member can not create a new user
        response = user_api_client.post(url, data=self.CREATE_DATA)
        assert response.status_code == 403

    def test_user_list_non_admin(self, user_api_client, rando):
        url = get_relative_url('user-list')
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1  # user can still see themselves
        assert 'rando' not in set(item['username'] for item in response.data['results'])

        response = user_api_client.post(url, data=self.CREATE_DATA)
        assert response.status_code == 403


@pytest.mark.django_db
class TestUserDetailView:
    def test_user_detail_works_superuser(self, admin_api_client, rando):
        url = get_relative_url('user-detail', kwargs={'pk': rando.pk})
        response = admin_api_client.get(url)
        assert response.status_code == 200

        user_response = admin_api_client.patch(url, data={})
        assert user_response.status_code == 200

    def test_org_admin_can_edit_user(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        rando = User.objects.create(username='rando')
        url = get_relative_url('user-detail', kwargs={'pk': rando.pk})

        response = user_api_client.get(url)
        assert response.status_code == 404

        org_member_rd.give_permission(rando, organization)
        org_member_rd.give_permission(user, organization)

        # Other members can see but not edit user
        response = user_api_client.get(url)
        assert response.status_code == 200

        response = user_api_client.patch(url, data={'email': 'foo@foo.invalid'})
        assert response.status_code == 403

        org_admin_rd.give_permission(user, organization)

        # Organization admins can edit users
        response = user_api_client.patch(url, data={'email': 'foo@foo.invalid'})
        assert response.status_code == 200

    @pytest.mark.parametrize('is_superuser', [False, True])
    def test_superuser_can_delete_new_user(self, admin_api_client, is_superuser):
        alice = User.objects.create(username='alice', is_superuser=is_superuser)
        url = get_relative_url('user-detail', kwargs={'pk': alice.pk})

        response = admin_api_client.delete(url)
        assert response.status_code == 204

    def test_user_can_not_delete_themselves(self, user, user_api_client, admin_user, admin_api_client):
        data = {
            user_api_client: get_relative_url('user-detail', kwargs={'pk': user.pk}),
            admin_api_client: get_relative_url('user-detail', kwargs={'pk': admin_user.pk}),
        }

        for api_client, url in data.items():
            response = api_client.delete(url)
            assert response.status_code == 403
            assert response.data['detail'] == "You can't delete yourself", user.username


@pytest.mark.django_db
class TestRoleBasedAssignment:
    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True)
    def test_org_admins_can_add_members(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        rando = User.objects.create(username='rando')
        unrelated_org = Organization.objects.create(name='another-org')
        org_admin_rd.give_permission(user, unrelated_org)  # setup permissions so user can see rando
        url = get_relative_url('roleuserassignment-list')

        org_member_rd.give_permission(user, organization)

        data = {'role_definition': org_member_rd.id, 'object_id': organization.id, 'user': rando.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 403, response.data
        assert not rando.has_obj_perm(organization, 'member')  # sanity, verify atomicity

        org_admin_rd.give_permission(user, organization)

        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(organization, 'member')

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES=True)
    @pytest.mark.parametrize(
        'holder_has_view_team, cache_parent_permissions, expect_success',
        [
            pytest.param(True, False, True, id='has-perm-no-cache'),
            pytest.param(True, True, True, id='has-perm-with-cache'),
            pytest.param(False, False, False, id='no-perm-blocked'),
        ],
    )
    def test_escalation_check_with_child_model_permissions(
        self, user, user_api_client, organization, holder_has_view_team, cache_parent_permissions, expect_success
    ):
        """The escalation check must correctly resolve child-model permissions (like view_team)
        that are included in org-scoped roles. A user holding an org role that includes view_team
        should be able to assign another org role that also includes view_team. A user whose
        org role does NOT include view_team should be blocked from assigning a role that does.

        When ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS is True, child-model permissions get
        RoleEvaluation entries on the parent object, so has_obj_perm can find them directly.
        When False (default), the escalation check must still resolve them correctly."""
        org_ct = DABContentType.objects.get_for_model(Organization)

        holder_perms = ['change_organization', 'view_organization']
        if holder_has_view_team:
            holder_perms.append('view_team')

        with override_settings(ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS=cache_parent_permissions):
            holder_rd = RoleDefinition.objects.create_from_permissions(name='custom-org-holder', permissions=holder_perms, content_type=org_ct)

            assignee_rd = RoleDefinition.objects.create_from_permissions(
                name='custom-org-assignee', permissions=['view_organization', 'view_team'], content_type=org_ct
            )

            holder_rd.give_permission(user, organization)
            rando = User.objects.create(username='rando')
            url = get_relative_url('roleuserassignment-list')
            data = {'role_definition': assignee_rd.id, 'object_id': organization.id, 'user': rando.id}

            response = user_api_client.post(url, data=data)
            if expect_success:
                assert response.status_code == 201, response.data
            else:
                assert response.status_code == 403, response.data

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True, ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES=True)
    @pytest.mark.parametrize(
        'team_role_has_view_team, expect_success',
        [
            pytest.param(True, True, id='team-has-perm'),
            pytest.param(False, False, id='team-no-perm'),
        ],
    )
    def test_escalation_check_with_team_inherited_permissions(self, user, user_api_client, organization, member_rd, team_role_has_view_team, expect_success):
        """Same escalation check, but the user's permissions come from team membership
        rather than a direct role assignment. The user is a member of a team, and the team
        has a role on the org. The escalation check must traverse team inheritance."""
        org_ct = DABContentType.objects.get_for_model(Organization)

        team_perms = ['change_organization', 'view_organization']
        if team_role_has_view_team:
            team_perms.append('view_team')
        team_rd = RoleDefinition.objects.create_from_permissions(name='custom-org-team-role', permissions=team_perms, content_type=org_ct)

        assignee_rd = RoleDefinition.objects.create_from_permissions(
            name='custom-org-assignee-via-team', permissions=['view_organization', 'view_team'], content_type=org_ct
        )

        team = Team.objects.create(name='holder-team', organization=organization)
        team_rd.give_permission(team, organization)
        member_rd.give_permission(user, team)

        rando = User.objects.create(username='rando')
        url = get_relative_url('roleuserassignment-list')
        data = {'role_definition': assignee_rd.id, 'object_id': organization.id, 'user': rando.id}

        response = user_api_client.post(url, data=data)
        if expect_success:
            assert response.status_code == 201, response.data
        else:
            assert response.status_code == 403, response.data

    @override_settings(
        ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True,
        ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES=True,
        ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES=True,
    )
    def test_escalation_check_with_global_role(self, user, user_api_client, organization):
        """A user holding a global (content_type=None) role that includes the needed
        permissions should be able to assign an org-scoped role containing those same
        permissions, even though the permissions were not granted at the object level."""
        org_ct = DABContentType.objects.get_for_model(Organization)

        global_rd = RoleDefinition.objects.create_from_permissions(
            name='global-with-view-team',
            permissions=['change_organization', 'view_organization', 'view_team'],
            content_type=None,
        )

        assignee_rd = RoleDefinition.objects.create_from_permissions(
            name='custom-org-assignee-via-global', permissions=['view_organization', 'view_team'], content_type=org_ct
        )

        global_rd.give_global_permission(user)

        rando = User.objects.create(username='rando')
        url = get_relative_url('roleuserassignment-list')
        data = {'role_definition': assignee_rd.id, 'object_id': organization.id, 'user': rando.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True)
    def test_escalation_check_with_parent_object_permissions(self, user, user_api_client, organization, org_admin_rd, member_rd):
        """An org admin assigns the Team Member role on a team within their org.
        The org admin's permissions come from an ObjectRole on the organization,
        not on the team itself. The escalation check must recognize that the org
        admin holds member_team and view_team via their org-scoped role."""
        team = Team.objects.create(name='test-team', organization=organization)
        org_admin_rd.give_permission(user, organization)

        rando = User.objects.create(username='rando')
        url = get_relative_url('roleuserassignment-list')
        data = {'role_definition': member_rd.id, 'object_id': team.id, 'user': rando.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data

    @override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True)
    def test_team_admins_can_add_children(self, user, user_api_client, organization, inventory, inv_rd, admin_rd, member_rd):
        url = get_relative_url('roleteamassignment-list')

        parent_team = Team.objects.create(name='parent', organization=organization)
        child_team = Team.objects.create(name='child', organization=organization)
        data = {'role_definition': member_rd.id, 'object_id': child_team.id, 'team': parent_team.id}
        # set up permissions for resource, this permission will be connected with the team assignment
        rando = User.objects.create(username='rando')
        member_rd.give_permission(rando, parent_team)
        inv_rd.give_permission(child_team, inventory)
        assert not rando.has_obj_perm(inventory, 'change')

        # (1) user can not view the team receiving the permission, cannot make assignment
        member_rd.give_permission(user, child_team)
        admin_rd.give_permission(user, child_team)
        response = user_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        assert 'object does not exist' in response.data['team'][0]
        admin_rd.remove_permission(user, child_team)  # hacky, need to test (1) in isolation of (2)

        # (2) user does not have admin permissions to the target (child) team, cannot make assignment
        member_rd.give_permission(user, parent_team)
        response = user_api_client.post(url, data=data)
        assert response.status_code == 403, response.data

        # (3) with admin permission to child team and view permission to parent, can make assignment
        admin_rd.give_permission(user, child_team)
        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')
