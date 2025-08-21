import pytest

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import Team, User


@pytest.mark.django_db
def test_user_access_list(admin_api_client, inv_rd, org_inv_rd, inventory, member_rd):
    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})

    u1 = User.objects.create(username='direct-inv-access', first_name='user', last_name='one')
    inv_rd.give_permission(u1, inventory)

    u2 = User.objects.create(username='org-level-access')
    org_inv_rd.give_permission(u2, inventory.organization)

    u3 = User.objects.create(username='team-via-access')
    team = Team.objects.create(name='proxy-team', organization=inventory.organization)
    inv_rd.give_permission(team, inventory)
    member_rd.give_permission(u3, team)

    response = admin_api_client.get(url)
    assert response.status_code == 200

    user_data = {}
    for user_detail in response.data['results']:
        user_data[user_detail['username']] = user_detail['object_role_assignments']
        assert 'related' in user_detail
        assert 'details' in user_detail['related']
        detail_resp = admin_api_client.get(user_detail['related']['details'])
        assert detail_resp.status_code == 200, detail_resp.data
        # This should have the same entries in a list view as the access list had in the assignments list
        assert detail_resp.data['count'] == len(user_detail['object_role_assignments'])
        if user_detail['username'] == u1.username:
            assert user_detail['first_name'] == 'user'
            assert user_detail['last_name'] == 'one'

    assert u1.username in user_data
    assert len(user_data[u1.username]) == 1
    assert user_data[u1.username][0]['type'] == 'direct'

    assert u2.username in user_data
    assert len(user_data[u2.username]) == 1
    assert user_data[u2.username][0]['type'] == 'indirect'

    assert u3.username in user_data
    assert len(user_data[u3.username]) == 1
    assert user_data[u3.username][0]['type'] == 'team'


@pytest.mark.django_db
def test_team_access_list(admin_api_client, inv_rd, org_inv_rd, inventory):
    url = get_relative_url('role-team-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})

    t1 = Team.objects.create(name='org-access', organization=inventory.organization)
    org_inv_rd.give_permission(t1, inventory.organization)

    t2 = Team.objects.create(name='direct-access', organization=inventory.organization)
    inv_rd.give_permission(t2, inventory)

    response = admin_api_client.get(url)
    assert response.status_code == 200

    team_data = {}
    for team_detail in response.data['results']:
        team_data[team_detail['name']] = team_detail['object_role_assignments']

        assert 'related' in team_detail
        assert 'details' in team_detail['related']
        detail_resp = admin_api_client.get(team_detail['related']['details'])
        assert detail_resp.status_code == 200, detail_resp.data
        # This should have the same entries in a list view as the access list had in the assignments list
        assert detail_resp.data['count'] == len(team_detail['object_role_assignments'])

    assert t1.name in team_data
    assert len(team_data[t1.name]) == 1
    assert team_data[t1.name][0]['type'] == 'indirect'

    assert t2.name in team_data
    assert len(team_data[t2.name]) == 1
    assert team_data[t2.name][0]['type'] == 'direct'


@pytest.mark.django_db
def test_intermediary_role_display(admin_api_client, inventory, organization, member_rd, rando):
    team = Team.objects.create(name='has_org_roles', organization=inventory.organization)

    org_admin_inv_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'add_inventory', 'change_inventory', 'delete_inventory', 'view_inventory'],
        name='org-inv-admin-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(organization),
    )
    org_view_inv_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_inventory'],
        name='org-inv-view-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(organization),
    )

    org_admin_inv_rd.give_permission(team, inventory.organization)
    org_view_inv_rd.give_permission(team, inventory.organization)
    member_rd.give_permission(rando, team)

    url = get_relative_url('role-user-access-assignments', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory', 'actor_pk': rando.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data

    assert response.data['count'] == 1
    assignment = response.data['results'][0]

    assert 'intermediary_roles' in assignment
    intermediary = assignment['intermediary_roles']
    assert len(intermediary) == 2
    intermediary_names = [entry['role_definition']['name'] for entry in intermediary]
    assert org_admin_inv_rd.name in intermediary_names
    assert org_view_inv_rd.name in intermediary_names


@pytest.mark.django_db
def test_no_duplicates(rando, inv_rd, inventory, org_inv_rd, admin_api_client):
    inv_rd.give_permission(rando, inventory)
    org_inv_rd.give_permission(rando, inventory.organization)

    # the admin user themselves will show up, so filter superusers out
    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'}) + '?is_superuser=false'
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1, response.data


@pytest.mark.django_db
def test_no_duplicates_team(team, inv_rd, inventory, org_inv_rd, admin_api_client):
    inv_rd.give_permission(team, inventory)
    org_inv_rd.give_permission(team, inventory.organization)

    url = get_relative_url('role-team-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1, response.data
