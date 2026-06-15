import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils.http import urlencode

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import Resource


@pytest.mark.django_db
class TestAnsibleIdAliasFilterBackend:

    def test_filter_user_ansible_id(self, admin_api_client, org_inv_rd, inv_rd, inventory, rando, random_user, organization):
        '''
        Test filtering RoleUserAssignment by user_ansible_id and object_ansible_id.
        Also test that other filtering works,
        '''
        # rando - org assigment
        user_resource = Resource.objects.get(object_id=rando.pk, content_type=ContentType.objects.get_for_model(rando).pk)
        organization_resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization).pk)
        url = get_relative_url('roleuserassignment-list')
        data = dict(role_definition=org_inv_rd.id, content_type='shared.organization', user_ansible_id=user_resource.ansible_id, object_id=organization.id)
        response = admin_api_client.post(url, data=data, format="json")
        assert response.status_code == 201, response.data

        # random_user - org assigment
        data = dict(role_definition=org_inv_rd.id, content_type='shared.organization', user=random_user.id, object_id=organization.id)
        response = admin_api_client.post(url, data=data, format="json")
        assert response.status_code == 201, response.data

        # rando - inventory assignment (an additional assignment to make total count > 1)
        data = dict(role_definition=inv_rd.id, content_type='aap.inventory', user_ansible_id=user_resource.ansible_id, object_id=inventory.id)
        response = admin_api_client.post(url, data=data, format="json")
        assert response.status_code == 201, response.data

        # make sure > 1 assignments total to ensure filtering is not returning undesired results
        response = admin_api_client.get(url)
        assert len(response.data["results"]) > 1, response.data

        # filter by user_ansible_id
        query_params = {'user_ansible_id': user_resource.ansible_id}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert len(response.data["results"]) == 2, response.data

        # filter by object_ansible_id
        query_params = {'object_ansible_id': organization_resource.ansible_id}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert len(response.data["results"]) == 2, response.data

        # filter by both user_ansible_id and object_ansible_id
        query_params = {'user_ansible_id': user_resource.ansible_id, 'object_ansible_id': organization_resource.ansible_id}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert len(response.data["results"]) == 1, response.data

        # filter by random user id
        query_params = {'user': random_user.id}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert len(response.data["results"]) == 1, response.data

    def test_filter_by_user_id(self, admin_api_client, inv_rd, inventory, random_user):
        '''
        Test that filtering with user id still works.
        This ensures that the default rest filters are still functional for this
        viewset.
        '''
        user_resource = Resource.objects.get(object_id=random_user.pk, content_type=ContentType.objects.get_for_model(random_user).pk)
        url = get_relative_url('roleuserassignment-list')
        data = dict(role_definition=inv_rd.id, content_type='aap.inventory', user_ansible_id=user_resource.ansible_id, object_id=inventory.id)
        response = admin_api_client.post(url, data=data, format="json")
        assert response.status_code == 201, response.data

        # filter by user_id
        query_params = {'user': random_user.id}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert len(response.data["results"]) == 1, response.data

        # filter by user_ansible_id
        query_params = {'user_ansible_id': user_resource.ansible_id}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert len(response.data["results"]) == 1, response.data

    def test_filter_team_ansible_id(self, admin_api_client, team, inv_rd, inventory):
        '''
        Test filtering RoleTeamAssignment by team_ansible_id.
        '''
        team_resource = Resource.objects.get(object_id=team.pk, content_type=ContentType.objects.get_for_model(team).pk)
        url = get_relative_url('roleteamassignment-list')
        data = dict(role_definition=inv_rd.id, content_type='shared.organization', team_ansible_id=team_resource.ansible_id, object_id=inventory.id)
        response = admin_api_client.post(url, data=data, format="json")
        assert response.status_code == 201, response.data

        # filter by team_ansible_id
        query_params = {'team_ansible_id': team_resource.ansible_id}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert len(response.data["results"]) == 1, response.data

    @pytest.mark.parametrize("ansible_id_type", ["user", "team", "object"])
    def test_invalid_ansible_id_format(self, admin_api_client, ansible_id_type):
        '''
        Test that invalid UUID formats for ansible_id raise a 400 error.
        '''
        if ansible_id_type == "team":
            actor = "team"
        else:
            actor = "user"
        url = get_relative_url(f'role{actor}assignment-list')
        query_params = {f'{ansible_id_type}_ansible_id': 'invalid-uuid-format'}
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 400, response.data
        assert "Invalid UUID format for" in str(response.data), response.data
