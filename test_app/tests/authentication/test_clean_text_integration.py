"""Tests that CleanTextMixin is correctly wired to DAB authentication serializers."""

from unittest.mock import MagicMock

import pytest
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import Authenticator, AuthenticatorMap
from ansible_base.authentication.serializers.authenticator_map import AuthenticatorMapSerializer
from ansible_base.lib.utils.response import get_relative_url

DANGEROUS_NAME = '<script>alert(1)</script>'
DANGEROUS_TEXT = '$(rm -rf /)'
GITHUB_ORG_TYPE = 'ansible_base.authentication.authenticator_plugins.github_org'

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _enable_enhanced_validation(settings):
    settings.ENHANCED_INPUT_VALIDATION_ENABLED = True


class TestAuthenticatorCleanText:

    def test_rejects_invalid_name_on_create(self, admin_api_client):
        url = get_relative_url('authenticator-list')
        data = {
            'name': DANGEROUS_NAME,
            'type': 'ansible_base.authentication.authenticator_plugins.local',
            'configuration': {},
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    def test_accepts_valid_name_on_create(self, admin_api_client):
        url = get_relative_url('authenticator-list')
        data = {
            'name': 'New Local Auth',
            'type': 'ansible_base.authentication.authenticator_plugins.local',
            'configuration': {},
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201

    def test_grandfather_unchanged_name_on_update(self, admin_api_client):
        url = get_relative_url('authenticator-list')
        response = admin_api_client.post(
            url,
            data={
                'name': 'Temp Auth For Grandfather',
                'type': 'ansible_base.authentication.authenticator_plugins.local',
                'configuration': {},
            },
            format='json',
        )
        assert response.status_code == 201
        auth_id = response.data['id']

        Authenticator.objects.filter(pk=auth_id).update(name='name;semicolon')

        detail_url = get_relative_url('authenticator-detail', kwargs={'pk': auth_id})
        response = admin_api_client.patch(detail_url, data={'name': 'name;semicolon'}, format='json')
        assert response.status_code == 200

    def test_rejects_changed_invalid_name_on_update(self, admin_api_client, local_authenticator):
        detail_url = get_relative_url('authenticator-detail', kwargs={'pk': local_authenticator.pk})
        response = admin_api_client.patch(detail_url, data={'name': DANGEROUS_NAME}, format='json')
        assert response.status_code == 400
        assert 'name' in response.data


class TestAuthenticatorConfigJsonCleanText:
    """Verify excluded_json_keys skips encrypted sub-keys while validating others."""

    def test_rejects_dangerous_value_in_non_excluded_config_key(self, admin_api_client):
        """NAME is not in excluded_json_keys and should be validated."""
        url = get_relative_url('authenticator-list')
        data = {
            'name': 'GitHub Org Auth',
            'type': GITHUB_ORG_TYPE,
            'configuration': {
                'CALLBACK_URL': 'https://localhost/api/gateway/callback/test/',
                'KEY': '12345',
                'SECRET': 'abcdefg12345',
                'NAME': DANGEROUS_NAME,
            },
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'configuration' in response.data
        assert 'NAME' in response.data['configuration']

    def test_accepts_dangerous_value_in_excluded_config_key(self, admin_api_client):
        """SECRET is in excluded_json_keys and should be skipped."""
        url = get_relative_url('authenticator-list')
        data = {
            'name': 'GitHub Org Auth Excluded',
            'type': GITHUB_ORG_TYPE,
            'configuration': {
                'CALLBACK_URL': 'https://localhost/api/gateway/callback/test/',
                'KEY': '12345',
                'SECRET': DANGEROUS_TEXT,
                'NAME': 'valid-org',
            },
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201

    def test_accepts_valid_config_values(self, admin_api_client):
        url = get_relative_url('authenticator-list')
        data = {
            'name': 'GitHub Org Auth Valid',
            'type': GITHUB_ORG_TYPE,
            'configuration': {
                'CALLBACK_URL': 'https://localhost/api/gateway/callback/test/',
                'KEY': '12345',
                'SECRET': 'abcdefg12345',
                'NAME': 'my-organization',
            },
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201


class TestAuthenticatorMapCleanText:

    def test_rejects_invalid_name_on_create(self, admin_api_client, local_authenticator):
        url = get_relative_url('authenticatormap-list')
        data = {
            'name': DANGEROUS_NAME,
            'authenticator': local_authenticator.id,
            'map_type': 'is_superuser',
            'triggers': {"always": {}},
            'order': 1,
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    @pytest.fixture
    def map_serializer(self):
        s = AuthenticatorMapSerializer()
        s.validate_trigger_data = MagicMock(return_value={})
        return s

    def test_rejects_invalid_name_at_serializer_level(self, map_serializer):
        with pytest.raises(ValidationError) as exc_info:
            map_serializer.validate(dict(name=DANGEROUS_NAME, map_type='is_superuser'))
        assert 'name' in exc_info.value.detail

    def test_accepts_valid_name(self, map_serializer):
        data = map_serializer.validate(dict(name='Valid Rule', map_type='is_superuser'))
        assert data['name'] == 'Valid Rule'

    def test_excluded_fields_accept_dangerous_content(self, map_serializer):
        """organization, role, team are excluded because they accept template syntax."""
        map_serializer.validate_role_data = MagicMock(return_value={})
        data = map_serializer.validate(
            dict(
                name='Valid Rule',
                map_type='team',
                organization='$(dangerous)',
                role='${EVIL}',
                team='<script>alert(1)</script>',
            )
        )
        assert data is not None

    def test_grandfather_unchanged_name_on_update(self, map_serializer, local_authenticator):
        auth_map = AuthenticatorMap.objects.create(
            name='name;semicolon',
            authenticator=local_authenticator,
            map_type='is_superuser',
            triggers={"always": {}},
            order=99,
        )
        serializer = AuthenticatorMapSerializer(instance=auth_map)
        serializer.validate_trigger_data = MagicMock(return_value={})
        data = serializer.validate(dict(name='name;semicolon', map_type='is_superuser', order=100))
        assert data['name'] == 'name;semicolon'
