import pytest
from django.test import override_settings
from django.urls import reverse

from test_app.models import User


@pytest.mark.django_db
class TestUserListView:
    CREATE_DATA = {'username': 'created-user', 'email': 'foo@foo.invalid', 'password': '$$$@@AAzzzz'}

    def test_user_list_superuser(self, admin_api_client, rando):
        url = reverse('user-list')
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 2  # Count needs to be fixed due to duplicated user issue

        response = admin_api_client.post(url, data=self.CREATE_DATA)
        assert response.status_code == 201
        assert User.objects.filter(username='created-user').exists()

    def test_org_admin_can_create_user(self, user, user_api_client, organization, org_admin_rd):
        url = reverse('user-list')
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

    @pytest.mark.parametrize('admin_setting', [True, False])
    def test_org_admin_setting(self, user, user_api_client, org_admin_rd, organization, admin_setting):
        org_admin_rd.give_permission(user, organization)
        User.objects.create(username='rando')  # not in organization
        url = reverse('user-list')
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
        url = reverse('user-list')

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
        url = reverse('user-list')
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1  # user can still see themselves
        assert 'rando' not in set(item['username'] for item in response.data['results'])

        response = user_api_client.post(url, data=self.CREATE_DATA)
        assert response.status_code == 403


@pytest.mark.django_db
class TestUserDetailView:
    def test_user_detail_works_superuser(self, admin_api_client, rando):
        url = reverse('user-detail', kwargs={'pk': rando.pk})
        response = admin_api_client.get(url)
        assert response.status_code == 200

        user_response = admin_api_client.patch(url, data={})
        assert user_response.status_code == 200

    def test_org_admin_can_edit_user(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        rando = User.objects.create(username='rando')
        url = reverse('user-detail', kwargs={'pk': rando.pk})

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


@pytest.mark.django_db
class TestRoleBasedAssignment:
    def test_org_admins_can_add_members(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        rando = User.objects.create(username='rando')
        url = reverse('roleuserassignment-list')

        org_member_rd.give_permission(user, organization)

        data = {'role_definition': org_member_rd.id, 'object_id': organization.id, 'user': rando.id}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 403, response.data
        assert not rando.has_obj_perm(organization, 'member')  # sanity, verify atomicity

        org_admin_rd.give_permission(user, organization)

        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(organization, 'member')


# TO TEST
# api/v1/ ^organizations/(?P<pk>[0-9]+)/members/$ [name='organization-users-list']
# api/v1/ ^organizations/(?P<pk>[0-9]+)/members/associate/$ [name='organization-users-associate']
# api/v1/ ^organizations/(?P<pk>[0-9]+)/members/disassociate/$ [name='organization-users-disassociate']
# api/v1/ ^organizations/(?P<pk>[0-9]+)/admins/$ [name='organization-admins-list']
# api/v1/ ^organizations/(?P<pk>[0-9]+)/admins/associate/$ [name='organization-admins-associate']
# api/v1/ ^organizations/(?P<pk>[0-9]+)/admins/disassociate/$ [name='organization-admins-disassociate']


@pytest.mark.django_db
class TestRelationshipBasedAssignment:
    """Tests permissions via tracked_relationship feature, duplicated functionality with TestRoleBasedAssignment

    Philosophically, this should perform the same actions and make the same assertions as TestRoleBasedAssignment
    because under the hood, signals are used to make these memberships exactly the same
    as the corresponding role assignments
    """

    def test_parent_object_view_permission(self, user, user_api_client, organization, org_member_rd):
        url = reverse('organization-list')
        response = user_api_client.get(url)
        assert response.data['count'] == 0

        url = reverse('organization-users-list', kwargs={'pk': organization.pk})
        response = user_api_client.get(url)
        assert response.status_code == 404, response.data

        org_member_rd.give_permission(user, organization)
        response = user_api_client.get(url)
        assert response.status_code == 200, response.data
        assert user.username in set(item['username'] for item in response.data['results'])

    def test_org_admins_can_add_members(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        rando = User.objects.create(username='rando')
        url = reverse('organization-users-associate', kwargs={'pk': organization.pk})

        org_member_rd.give_permission(user, organization)

        data = {'instances': [rando.id]}

        response = user_api_client.post(url, data=data)
        assert response.status_code == 403, response.data
        assert not rando.has_obj_perm(organization, 'member')  # sanity, verify atomicity

        org_admin_rd.give_permission(user, organization)

        response = user_api_client.post(url, data=data)
        assert response.status_code == 204, response.data
        assert rando.has_obj_perm(organization, 'member')
