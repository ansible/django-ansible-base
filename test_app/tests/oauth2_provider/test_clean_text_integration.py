"""Tests that CleanTextMixin is correctly wired to DAB OAuth2 serializers."""

import pytest

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2Application

DANGEROUS_NAME = '<script>alert(1)</script>'
DANGEROUS_TEXT = '$(rm -rf /)'


@pytest.mark.django_db
class TestOAuth2ApplicationCleanText:

    def test_rejects_invalid_name_on_create(self, admin_api_client, organization):
        url = get_relative_url('application-list')
        data = {
            'name': DANGEROUS_NAME,
            'organization': organization.pk,
            'authorization_grant_type': 'password',
            'client_type': 'confidential',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    def test_rejects_invalid_description_on_create(self, admin_api_client, organization):
        url = get_relative_url('application-list')
        data = {
            'name': 'Valid OAuth2 App',
            'description': DANGEROUS_TEXT,
            'organization': organization.pk,
            'authorization_grant_type': 'password',
            'client_type': 'confidential',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'description' in response.data

    def test_accepts_valid_data_on_create(self, admin_api_client, organization):
        url = get_relative_url('application-list')
        data = {
            'name': 'My OAuth2 App',
            'description': 'A valid description',
            'organization': organization.pk,
            'authorization_grant_type': 'password',
            'client_type': 'confidential',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201

    def test_grandfather_unchanged_name_on_update(self, admin_api_client, oauth2_application):
        app, _ = oauth2_application
        OAuth2Application.objects.filter(pk=app.pk).update(name='name;semicolon')

        url = get_relative_url('application-detail', args=[app.pk])
        response = admin_api_client.patch(url, data={'name': 'name;semicolon', 'description': 'Updated desc'}, format='json')
        assert response.status_code == 200


@pytest.mark.django_db
class TestOAuth2TokenCleanText:
    # No grandfather test: OAuth2 tokens are not updated via PATCH — most fields
    # (token, expires, refresh_token, user) are read-only.

    def test_rejects_invalid_description_on_create(self, admin_api_client, oauth2_application):
        app, _ = oauth2_application
        url = get_relative_url('token-list')
        data = {
            'scope': 'read',
            'description': DANGEROUS_TEXT,
            'application': app.pk,
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'description' in response.data

    def test_accepts_valid_description_on_create(self, admin_api_client, oauth2_application):
        app, _ = oauth2_application
        url = get_relative_url('token-list')
        data = {
            'scope': 'read',
            'description': 'My personal access token',
            'application': app.pk,
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201
