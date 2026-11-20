import pytest
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url
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
class TestUserSelfEditAAP66511:
    """Regression coverage for AAP-66511: a normal local user must be able to
    manage their own record (e.g. change their own password) regardless of
    MANAGE_ORGANIZATION_AUTH, while admin-only fields (is_active) stay
    protected. Payload shape mirrors what ansible-ui actually sends: the
    whole user object, with unrelated fields (is_active) resent unchanged
    and no password key at all unless the user is genuinely changing it.
    """

    @override_settings(MANAGE_ORGANIZATION_AUTH=False)
    def test_self_edit_whole_object_payload_succeeds(self, user, user_api_client):
        url = get_relative_url('user-detail', kwargs={'pk': user.pk})
        response = user_api_client.patch(url, data={'first_name': 'Updated', 'is_active': user.is_active})
        assert response.status_code == 200, response.data

        user.refresh_from_db()
        assert user.first_name == 'Updated'
        assert user.is_active is True

    @override_settings(MANAGE_ORGANIZATION_AUTH=False)
    def test_self_password_change_succeeds(self, user, user_api_client):
        url = get_relative_url('user-detail', kwargs={'pk': user.pk})
        response = user_api_client.patch(url, data={'password': 'NewSecurePass1!'})
        assert response.status_code == 200, response.data

    @override_settings(MANAGE_ORGANIZATION_AUTH=False)
    def test_self_edit_cannot_also_flip_is_active(self, user, user_api_client):
        """A whole-object self-edit must not let a regular user smuggle in an
        is_active change alongside an otherwise-legitimate profile update."""
        url = get_relative_url('user-detail', kwargs={'pk': user.pk})
        response = user_api_client.patch(url, data={'first_name': 'Updated', 'is_active': not user.is_active})
        assert response.status_code == 403, response.data

        user.refresh_from_db()
        assert user.first_name != 'Updated'
        assert user.is_active is True

    @override_settings(MANAGE_ORGANIZATION_AUTH=True)
    def test_self_edit_still_works_with_manage_org_auth_enabled(self, user, user_api_client):
        """Sanity check: the fix is additive, not a behavior change when
        MANAGE_ORGANIZATION_AUTH is enabled (the normal/default case)."""
        url = get_relative_url('user-detail', kwargs={'pk': user.pk})
        response = user_api_client.patch(url, data={'password': 'NewSecurePass1!'})
        assert response.status_code == 200, response.data

    @override_settings(MANAGE_ORGANIZATION_AUTH=False)
    def test_self_password_change_is_recorded_in_activity_stream(self, user, user_api_client):
        """AC #7: fixing the access issue must not bypass audit logging --
        a self-service password change still produces an activity stream
        entry, with the value masked rather than leaked in plaintext."""
        url = get_relative_url('user-detail', kwargs={'pk': user.pk})
        response = user_api_client.patch(url, data={'password': 'NewSecurePass1!'})
        assert response.status_code == 200, response.data

        entry = user.activity_stream_entries.last()
        assert entry is not None
        assert 'password' in entry.changes['changed_fields']
        assert 'NewSecurePass1!' not in str(entry.changes)


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
