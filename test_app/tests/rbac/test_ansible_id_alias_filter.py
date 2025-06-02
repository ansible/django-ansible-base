import pytest
from django.utils.http import urlencode

from ansible_base.lib.utils.response import get_relative_url
from django.contrib.contenttypes.models import ContentType
from ansible_base.resource_registry.models import Resource


class TestAnsibleIdAliasFilterBackend:

    @pytest.mark.django_db
    def test_filter_user_ansible_id(self, admin_api_client, org_inv_rd, rando, organization):
        user_resource = Resource.objects.get(object_id=rando.pk, content_type=ContentType.objects.get_for_model(rando).pk)
        organization_resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization).pk)
        url = get_relative_url('roleuserassignment-list')
        data = dict(role_definition=org_inv_rd.id, content_type='shared.organization', user_ansible_id=user_resource.ansible_id, object_id=organization.id)
        response = admin_api_client.post(url, data=data, format="json")
        assert response.status_code == 201, response.data

        # filter by user_ansible_id
        query_params = {
            'user_ansible_id': user_resource.ansible_id
        }
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert response.data["count"] == 1, response.data

        # filter by object_ansible_id
        query_params = {
            'object_ansible_id': organization_resource.ansible_id
        }
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert response.data["count"] == 1, response.data

        # filter by both user_ansible_id and object_ansible_id
        query_params = {
            'user_ansible_id': user_resource.ansible_id,
            'object_ansible_id': organization_resource.ansible_id
        }
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert response.data["count"] == 1, response.data


    @pytest.mark.django_db
    def test_filter_team_ansible_id(self, admin_api_client, team, inv_rd, inventory):
        team_resource = Resource.objects.get(object_id=team.pk, content_type=ContentType.objects.get_for_model(team).pk)
        url = get_relative_url('roleteamassignment-list')
        data = dict(role_definition=inv_rd.id, content_type='shared.organization', team_ansible_id=team_resource.ansible_id, object_id=inventory.id)
        response = admin_api_client.post(url, data=data, format="json")
        assert response.status_code == 201, response.data

        # filter by team_ansible_id
        query_params = {
            'team_ansible_id': team_resource.ansible_id
        }
        response = admin_api_client.get(url + '?' + urlencode(query_params))
        assert response.status_code == 200, response.data
        assert response.data["count"] == 1, response.data
