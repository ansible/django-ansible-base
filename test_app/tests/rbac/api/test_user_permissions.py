import pytest

from django.urls import reverse

from test_app.models import User


@pytest.mark.django_db
def test_org_admin_can_create_user(user, user_api_client, organization, org_admin_rd):
    url = reverse('user-list')

    create_data = {'username': 'rando', 'email': 'foo@foo.invalid', 'password': '$$$@@AAzzzz'}

    response = user_api_client.post(url, data=create_data)
    assert response.status_code == 403
    assert not User.objects.filter(username='rando').exists()

    org_admin_rd.give_permission(user, organization)

    response = user_api_client.post(url, data=create_data)
    assert response.status_code == 201
    assert User.objects.filter(username='rando').exists()


@pytest.mark.django_db
def test_org_admin_can_edit_user(user, user_api_client, organization, org_member_rd, org_admin_rd):
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
def test_org_members_can_view_users(user, user_api_client, organization, org_member_rd):
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


@pytest.mark.django_db
def test_org_admins_can_add_members(user, user_api_client, organization, org_member_rd, org_admin_rd):
    rando = User.objects.create(username='rando')
    url = reverse('roleuserassignment-list')

    org_member_rd.give_permission(user, organization)

    data = {
        'role_definition': org_member_rd.id,
        'object_id': organization.id,
        'user': rando.id
    }

    response = user_api_client.post(url, data=data)
    assert response.status_code == 403
    assert not rando.has_obj_perm(organization, 'member')  # sanity, verify atomicity

    org_admin_rd.give_permission(user, organization)

    response = user_api_client.post(url, data=data)
    assert response.status_code == 201
    assert rando.has_obj_perm(organization, 'member')
