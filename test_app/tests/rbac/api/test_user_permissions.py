import pytest
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.policies import visible_users
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
        assert response.status_code == 400
        assert 'object does not exist' in response.data['team'][0]
        admin_rd.remove_permission(user, child_team)  # hacky, need to test (1) in isolation of (2)

        # (2) user does not have admin permissions to the target (child) team, cannot make assignment
        member_rd.give_permission(user, parent_team)
        response = user_api_client.post(url, data=data)
        assert response.status_code == 403

        # (3) with admin permission to child team and view permission to parent, can make assignment
        admin_rd.give_permission(user, child_team)
        response = user_api_client.post(url, data=data)
        assert response.status_code == 201
        assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
class TestRelatedUserListView:
    def _initial_check(self, url, user_api_client, count=0):
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == count

    def _assign_users(self, role_definition, object):
        members = [
            User.objects.create(username='rando1'),
            User.objects.create(username='rando2'),
            User.objects.create(username='rando3'),
        ]
        role_definition.give_permission(members[0], object)
        role_definition.give_permission(members[1], object)

    def test_org_admin_list_org_members(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        org_admin_rd.give_permission(user, organization)

        url = get_relative_url('organization-users-list', kwargs={'pk': organization.pk})
        self._initial_check(url, user_api_client)
        self._assign_users(org_member_rd, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 2

    def test_org_member_list_org_members(self, user, user_api_client, organization, org_member_rd):
        org_member_rd.give_permission(user, organization)

        url = get_relative_url('organization-users-list', kwargs={'pk': organization.pk})
        self._initial_check(url, user_api_client, 1)
        self._assign_users(org_member_rd, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 3

    def test_superadmin_list_org_members(self, user, user_api_client, organization, org_member_rd):
        user.is_superuser = True
        user.save()

        url = get_relative_url('organization-users-list', kwargs={'pk': organization.pk})
        self._initial_check(url, user_api_client)
        self._assign_users(org_member_rd, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 2


@pytest.mark.django_db
class TestRelationshipBasedAssignment:
    """Tests permissions via tracked_relationship feature, duplicated functionality with TestRoleBasedAssignment

    Philosophically, this should perform the same actions and make the same assertions as TestRoleBasedAssignment
    because under the hood, signals are used to make these memberships exactly the same
    as the corresponding role assignments
    """

    def test_parent_object_view_permission(self, user, user_api_client, organization, org_member_rd):
        url = get_relative_url('organization-list')
        response = user_api_client.get(url)
        assert response.data['count'] == 0

        url = get_relative_url('organization-users-list', kwargs={'pk': organization.pk})
        response = user_api_client.get(url)
        assert response.status_code == 404, response.data

        org_member_rd.give_permission(user, organization)
        response = user_api_client.get(url)
        assert response.status_code == 200, response.data
        assert user.username in set(item['username'] for item in response.data['results'])

    def test_org_admins_can_add_members(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        rando = User.objects.create(username='rando')
        url = get_relative_url('organization-users-associate', kwargs={'pk': organization.pk})

        org_member_rd.give_permission(user, organization)

        data = {'instances': [rando.id]}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 403, response.data
        assert not rando.has_obj_perm(organization, 'member')  # sanity, verify atomicity

        org_admin_rd.give_permission(user, organization)

        response = user_api_client.post(url, data=data)
        assert response.status_code == 204, response.data
        assert rando.has_obj_perm(organization, 'member')

    @override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=False)
    def test_associate_needs_view_permission(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        "Need view permission to user to associate to an organization"
        org_admin_rd.give_permission(user, organization)
        rando = User.objects.create(username='rando')
        assert not visible_users(user).filter(pk=rando.id).exists()  # sanity
        url = get_relative_url('organization-admins-associate', kwargs={'pk': organization.pk})

        data = {'instances': [rando.id]}

        # user can not see other user rando, should get related object does not exist error
        response = user_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        assert not rando.has_obj_perm(organization, 'change')

        org_member_rd.give_permission(rando, organization)
        assert visible_users(user).filter(pk=rando.id).exists()

        # user can see other user rando, and can make rando an organization admin
        response = user_api_client.post(url, data=data)
        assert response.status_code == 204, response.data
        assert rando.has_obj_perm(organization, 'change')  # action took full effect

    def test_sublist_visibility(self, user, user_api_client, team, member_rd, admin_rd):
        url = get_relative_url('team-users-list', kwargs={'pk': team.pk})

        # with no permissions, user should not be able to make a GET to members list
        response = user_api_client.get(url)
        assert response.status_code == 404

        rando = User.objects.create(username='rando')
        member_rd.give_permission(rando, team)
        admin_rd.give_permission(user, team)
        assert not visible_users(user).filter(pk=rando.id).exists()  # sanity

        # even though user can not see rando, they still show in members list
        # this would be important if user wanted to remove rando permissions
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert 'rando' in set(item['username'] for item in response.data['results'])

    @override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=False)
    def test_visible_users_flags(self, admin_user, user, team, member_rd):
        assert set(visible_users(user).values_list('id', flat=True)) == {admin_user.id, user.id}
        assert set(visible_users(user, always_show_superusers=False).values_list('id', flat=True)) == {user.id}
        assert set(visible_users(user, always_show_self=False).values_list('id', flat=True)) == {admin_user.id}
