"""Tests that CleanTextMixin is correctly wired to DAB RBAC serializers."""

import pytest
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition

DANGEROUS_NAME = '<script>alert(1)</script>'
DANGEROUS_TEXT = '$(rm -rf /)'


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestRoleDefinitionCleanText:

    def test_rejects_invalid_name_on_create(self, admin_api_client):
        url = get_relative_url('roledefinition-list')
        data = {
            'name': DANGEROUS_NAME,
            'description': 'A valid description',
            'permissions': ['shared.view_organization'],
            'content_type': 'shared.organization',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    def test_rejects_invalid_description_on_create(self, admin_api_client):
        url = get_relative_url('roledefinition-list')
        data = {
            'name': 'Valid Role Name',
            'description': DANGEROUS_TEXT,
            'permissions': ['shared.view_organization'],
            'content_type': 'shared.organization',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'description' in response.data

    def test_accepts_valid_data_on_create(self, admin_api_client):
        url = get_relative_url('roledefinition-list')
        data = {
            'name': 'My Custom Role',
            'description': 'A role for viewing organizations',
            'permissions': ['shared.view_organization'],
            'content_type': 'shared.organization',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201

    def test_grandfather_unchanged_name_on_update(self, admin_api_client):
        url = get_relative_url('roledefinition-list')
        response = admin_api_client.post(
            url,
            data={
                'name': 'Temp Role',
                'description': 'Original',
                'permissions': ['shared.view_organization'],
                'content_type': 'shared.organization',
            },
            format='json',
        )
        assert response.status_code == 201
        rd_id = response.data['id']

        RoleDefinition.objects.filter(pk=rd_id).update(name='name;semicolon')

        detail_url = get_relative_url('roledefinition-detail', kwargs={'pk': rd_id})
        response = admin_api_client.patch(detail_url, data={'name': 'name;semicolon', 'description': 'Updated'}, format='json')
        assert response.status_code == 200
