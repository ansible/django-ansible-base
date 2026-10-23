"""Tests that CleanTextMixin is correctly wired to DAB authentication serializers."""

from unittest.mock import MagicMock, patch

import pytest
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import Authenticator, AuthenticatorMap
from ansible_base.authentication.serializers.authenticator_map import AuthenticatorMapSerializer
from ansible_base.lib.serializers.mixins import _INCOMPLETE_VALIDATION_MSG, CleanTextMixin
from ansible_base.lib.utils.response import get_relative_url

DANGEROUS_NAME = '<script>alert(1)</script>'
DANGEROUS_TEXT = '$(rm -rf /)'
DANGEROUS_TEMPLATE = '{{malicious}}'
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

    def test_accepts_pem_certificate_values_in_config(self, admin_api_client, saml_configuration):
        """PEM-encoded certs (SP_PUBLIC_CERT, IDP_X509_CERT) must not trip the Tier 2 blocklist."""
        url = get_relative_url('authenticator-list')
        data = {
            'name': 'SAML Auth With Real Certs',
            'type': 'ansible_base.authentication.authenticator_plugins.saml',
            'configuration': saml_configuration,
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

    def test_expansion_syntax_accepted_in_expansion_fields(self, map_serializer):
        """Genuine {% for_attr_value(...) %} expansion syntax bypasses Tier 2 validation."""
        map_serializer.validate_role_data = MagicMock(return_value={})
        data = map_serializer.validate(
            dict(
                name='Valid Rule',
                map_type='team',
                organization='{% for_attr_value(user_orgs) %}',
                role='{% for_attr_value(user_role) %}',
                team='Team {% for_attr_value(member_of) %}',
            )
        )
        assert data['organization'] == '{% for_attr_value(user_orgs) %}'
        assert data['role'] == '{% for_attr_value(user_role) %}'
        assert data['team'] == 'Team {% for_attr_value(member_of) %}'

    def test_literal_dangerous_content_rejected_in_expansion_fields(self, map_serializer):
        """Literal (non-expansion) values in organization/role/team are validated like any other free-text field."""
        map_serializer.validate_role_data = MagicMock(return_value={})
        with pytest.raises(ValidationError) as exc_info:
            map_serializer.validate(
                dict(
                    name='Valid Rule',
                    map_type='team',
                    organization='$(dangerous)',
                    role='${EVIL}',
                    team='<script>alert(1)</script>',
                )
            )
        assert 'organization' in exc_info.value.detail
        assert 'role' in exc_info.value.detail
        assert 'team' in exc_info.value.detail

    def test_grandfather_unchanged_name_on_update_at_serializer_level(self, local_authenticator):
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

    def test_grandfather_unchanged_name_on_update(self, admin_api_client, local_authenticator):
        auth_map = AuthenticatorMap.objects.create(
            name='name;semicolon',
            authenticator=local_authenticator,
            map_type='is_superuser',
            triggers={"always": {}},
            order=99,
        )
        url = get_relative_url('authenticatormap-detail', kwargs={'pk': auth_map.pk})
        response = admin_api_client.patch(url, data={'name': 'name;semicolon', 'order': 100}, format='json')
        assert response.status_code == 200

    def test_rejects_changed_invalid_name_on_update(self, admin_api_client, local_authenticator):
        auth_map = AuthenticatorMap.objects.create(
            name='name;semicolon',
            authenticator=local_authenticator,
            map_type='is_superuser',
            triggers={"always": {}},
            order=1,
        )
        url = get_relative_url('authenticatormap-detail', kwargs={'pk': auth_map.pk})
        response = admin_api_client.patch(url, data={'name': DANGEROUS_NAME}, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    def test_rejects_dangerous_template_in_attribute_value(self, admin_api_client, local_authenticator):
        url = get_relative_url('authenticatormap-list')
        data = {
            'name': 'Attr value rule',
            'authenticator': local_authenticator.id,
            'map_type': 'is_superuser',
            'triggers': {'attributes': {'email': {'contains': DANGEROUS_TEMPLATE}}},
            'order': 1,
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'triggers' in response.data

    def test_rejects_dangerous_template_in_attribute_name(self, admin_api_client, local_authenticator):
        url = get_relative_url('authenticatormap-list')
        data = {
            'name': 'Attr name rule',
            'authenticator': local_authenticator.id,
            'map_type': 'is_superuser',
            'triggers': {'attributes': {DANGEROUS_TEMPLATE: {'contains': 'benign'}}},
            'order': 2,
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'triggers' in response.data
        assert f'attributes.{DANGEROUS_TEMPLATE}' in response.data['triggers']

    def test_grandfather_unchanged_attribute_name_on_update(self, admin_api_client, local_authenticator):
        auth_map = AuthenticatorMap.objects.create(
            name='Grandfather attr key',
            authenticator=local_authenticator,
            map_type='is_superuser',
            triggers={'attributes': {DANGEROUS_TEMPLATE: {'contains': 'ok'}}},
            order=3,
        )
        url = get_relative_url('authenticatormap-detail', kwargs={'pk': auth_map.pk})
        response = admin_api_client.patch(
            url,
            data={
                'triggers': {'attributes': {DANGEROUS_TEMPLATE: {'contains': 'still-ok'}}},
            },
            format='json',
        )
        assert response.status_code == 200

    def test_rejects_new_dangerous_attribute_name_on_update(self, admin_api_client, local_authenticator):
        auth_map = AuthenticatorMap.objects.create(
            name='New attr key on update',
            authenticator=local_authenticator,
            map_type='is_superuser',
            triggers={'attributes': {'email': {'contains': '@example.com'}}},
            order=4,
        )
        url = get_relative_url('authenticatormap-detail', kwargs={'pk': auth_map.pk})
        response = admin_api_client.patch(
            url,
            data={
                'triggers': {
                    'attributes': {
                        'email': {'contains': '@example.com'},
                        DANGEROUS_TEMPLATE: {'contains': 'x'},
                    },
                },
            },
            format='json',
        )
        assert response.status_code == 400
        assert f'attributes.{DANGEROUS_TEMPLATE}' in response.data['triggers']

    @pytest.mark.parametrize(
        'triggers',
        [
            'not-a-dict',
            {'groups': {'has_or': []}},
            {'attributes': 'not-a-dict'},
        ],
        ids=['non_dict_triggers', 'no_attributes', 'non_dict_attributes'],
    )
    def test_attribute_name_validation_noop_for_non_attribute_triggers(self, map_serializer, triggers):
        assert map_serializer._validate_trigger_attribute_name_keys(triggers) == {}

    def test_attribute_name_validation_skips_join_condition(self, map_serializer):
        triggers = {'attributes': {'join_condition': 'and', 'email': {'contains': 'x'}}}
        assert map_serializer._validate_trigger_attribute_name_keys(triggers) == {}

    def test_stored_trigger_attributes_from_instance(self, local_authenticator):
        auth_map = AuthenticatorMap.objects.create(
            name='Stored attrs',
            authenticator=local_authenticator,
            map_type='is_superuser',
            triggers={'attributes': {'email': {'contains': 'x'}}},
            order=5,
        )
        serializer = AuthenticatorMapSerializer(instance=auth_map)
        assert serializer._stored_trigger_attributes() == {'email': {'contains': 'x'}}

    def test_attribute_name_validation_reports_incomplete_on_unexpected_error(self, map_serializer):
        with patch(
            'ansible_base.authentication.serializers.authenticator_map.validate_free_text',
            side_effect=RuntimeError('validator crash'),
        ):
            result = map_serializer._validate_trigger_attribute_name_keys(
                {'attributes': {'new_attr': {'contains': 'x'}}},
            )
        assert result['attributes.new_attr'] == [_INCOMPLETE_VALIDATION_MSG]

    @pytest.mark.parametrize(
        'initial_triggers_errors,expect_merged',
        [
            (None, False),
            ({'attributes.email.contains': ['bad value']}, True),
            (['non-dict'], False),
        ],
        ids=['set_triggers_errors', 'merge_dict_errors', 'replace_non_dict_errors'],
    )
    def test_merge_trigger_attribute_key_errors(self, initial_triggers_errors, expect_merged):
        attr_key_errors = {f'attributes.{DANGEROUS_TEMPLATE}': ['blocked']}
        errors = {}
        if initial_triggers_errors is not None:
            errors['triggers'] = initial_triggers_errors
        AuthenticatorMapSerializer._merge_trigger_attribute_key_errors(errors, attr_key_errors)
        assert f'attributes.{DANGEROUS_TEMPLATE}' in errors['triggers']
        if expect_merged:
            assert 'attributes.email.contains' in errors['triggers']

    def test_validate_json_fields_merges_attribute_name_errors(self, map_serializer):
        attrs = {'triggers': {'attributes': {DANGEROUS_TEMPLATE: {'contains': 'ok'}}}}
        errors = {'triggers': {'attributes.email.contains': ['existing']}}
        with patch.object(CleanTextMixin, '_validate_json_fields', return_value=None):
            map_serializer._validate_json_fields(['triggers'], attrs, errors)
        assert f'attributes.{DANGEROUS_TEMPLATE}' in errors['triggers']
        assert 'attributes.email.contains' in errors['triggers']

    def test_validate_json_fields_skips_without_triggers_field(self, map_serializer):
        errors = {}
        map_serializer._validate_json_fields(['name'], {'name': 'x'}, errors)
        assert errors == {}

    def test_grandfather_attribute_name_via_stored_attributes(self, local_authenticator):
        auth_map = AuthenticatorMap.objects.create(
            name='Grandfather via helper',
            authenticator=local_authenticator,
            map_type='is_superuser',
            triggers={'attributes': {DANGEROUS_TEMPLATE: {'contains': 'ok'}}},
            order=6,
        )
        serializer = AuthenticatorMapSerializer(instance=auth_map)
        assert (
            serializer._validate_trigger_attribute_name_keys(
                {'attributes': {DANGEROUS_TEMPLATE: {'contains': 'changed'}}},
            )
            == {}
        )
