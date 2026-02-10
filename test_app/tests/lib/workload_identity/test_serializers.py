import pytest

from ansible_base.lib.workload_identity.workload_identity_tokens import (
    WorkloadIdentityTokenRequestSerializer,
    WorkloadIdentityTokenResponseSerializer,
)


@pytest.mark.django_db
class TestWorkloadIdentityTokenRequestSerializer:
    """
    Test suite for WorkloadIdentityTokenRequestSerializer.
    """

    def test_valid_data(self):
        """
        Test that valid data passes serializer validation.
        Uses the actual claim names that the Gateway expects (job_name, organization_name, etc.)
        as defined in aap_gateway_api.views.api.v1.workload_identity_tokens.TARGET_CLAIM_NAMES_TO_SUB_STUBS
        """
        valid_data = {
            'scope': 'openid profile',
            'audience': 'https://api.example.com',
            'claims': {
                'job_name': 'deploy-production',
                'organization_name': 'LaPaloma',
                'project_name': 'web-app',
                'job_template_name': 'deploy-template',
            },
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data == valid_data

    def test_missing_scope(self):
        """
        Test that missing scope field fails validation.
        """
        invalid_data = {
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'scope' in serializer.errors
        assert serializer.errors['scope'][0].code == 'required'

    def test_missing_audience(self):
        """
        Test that missing audience field fails validation.
        """
        invalid_data = {
            'scope': 'openid',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'audience' in serializer.errors
        assert serializer.errors['audience'][0].code == 'required'

    def test_missing_claims(self):
        """
        Test that missing claims field fails validation.
        """
        invalid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'claims' in serializer.errors
        assert serializer.errors['claims'][0].code == 'required'

    def test_null_scope(self):
        """
        Test that null scope fails validation.
        """
        invalid_data = {
            'scope': None,
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'scope' in serializer.errors
        assert serializer.errors['scope'][0].code == 'null'

    def test_null_audience(self):
        """
        Test that null audience fails validation.
        """
        invalid_data = {
            'scope': 'openid',
            'audience': None,
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'audience' in serializer.errors
        assert serializer.errors['audience'][0].code == 'null'

    def test_blank_scope(self):
        """
        Test that blank scope fails validation.
        """
        invalid_data = {
            'scope': '',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'scope' in serializer.errors
        assert serializer.errors['scope'][0].code == 'blank'

    def test_blank_audience(self):
        """
        Test that blank audience fails validation.
        """
        invalid_data = {
            'scope': 'openid',
            'audience': '',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'audience' in serializer.errors
        assert serializer.errors['audience'][0].code == 'blank'

    def test_null_claims(self):
        """
        Test that null claims fails validation.
        """
        invalid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': None,
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'claims' in serializer.errors
        assert serializer.errors['claims'][0].code == 'null'

    def test_empty_claims(self):
        """
        Test that empty claims dict fails validation.
        """
        invalid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'claims' in serializer.errors
        assert serializer.errors['claims'][0].code == 'empty'

    def test_claims_not_dict(self):
        """
        Test that non-dict claims fail validation.
        """
        invalid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': 'not-a-dict',
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'claims' in serializer.errors
        assert serializer.errors['claims'][0].code == 'not_a_dict'

    def test_nested_claims(self):
        """
        Test that nested claims are accepted.
        Note: While the Gateway expects specific top-level claim names, the serializer
        allows any structure including nested data for extensibility.
        """
        valid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {
                'job_name': 'deploy-prod',
                'organization_name': 'LaPaloma',
                'metadata': {
                    'created_by': 'user@example.com',
                    'tags': ['production', 'critical'],
                },
            },
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data == valid_data

    def test_multiple_scopes(self):
        """
        Test that multiple space-separated scopes are accepted.
        """
        valid_data = {
            'scope': 'openid profile email',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"

    def test_extra_fields_ignored(self):
        """
        Test that extra fields are ignored (not raising errors).
        """
        data_with_extra = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
            'extra_field': 'should be ignored',
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=data_with_extra)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        # Extra fields should not appear in validated_data
        assert 'extra_field' not in serializer.validated_data


@pytest.mark.django_db
class TestWorkloadIdentityTokenResponseSerializer:
    """
    Test suite for WorkloadIdentityTokenResponseSerializer.
    """

    def test_valid_jwt(self):
        """
        Test that valid JWT data passes serializer validation.
        """
        valid_data = {
            'jwt': (
                'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
                'eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.'
                'SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c'
            ),
        }
        serializer = WorkloadIdentityTokenResponseSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data == valid_data

    def test_missing_jwt(self):
        """
        Test that missing jwt field fails validation.
        """
        invalid_data = {}
        serializer = WorkloadIdentityTokenResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'jwt' in serializer.errors
        assert serializer.errors['jwt'][0].code == 'required'

    def test_null_jwt(self):
        """
        Test that null jwt fails validation.
        """
        invalid_data = {'jwt': None}
        serializer = WorkloadIdentityTokenResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'jwt' in serializer.errors
        assert serializer.errors['jwt'][0].code == 'null'

    def test_blank_jwt(self):
        """
        Test that blank jwt fails validation.
        """
        invalid_data = {'jwt': ''}
        serializer = WorkloadIdentityTokenResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'jwt' in serializer.errors
        assert serializer.errors['jwt'][0].code == 'blank'

    def test_jwt_with_whitespace(self):
        """
        Test that JWT with leading/trailing whitespace is removed.
        Note: DRF CharField trims whitespace by default, so this tests
        that the serializer removes the whitespace.
        """
        data_with_whitespace = {
            'jwt': ('  eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' 'eyJzdWIiOiIxMjM0NTY3ODkwIn0.' 'dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U  '),
        }
        serializer = WorkloadIdentityTokenResponseSerializer(data=data_with_whitespace)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert 'jwt' in serializer.validated_data
        # Verify whitespace is removed (DRF CharField default behavior)
        assert ' ' not in serializer.validated_data['jwt']

    def test_create_response_serializer(self):
        """
        Test creating a WorkloadIdentityTokenResponseSerializer instance with data.
        """
        jwt_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' 'eyJzdWIiOiIxMjM0NTY3ODkwIn0.' 'dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U'
        serializer = WorkloadIdentityTokenResponseSerializer({'jwt': jwt_token})
        # This is a non-validated instance
        assert serializer.data == {'jwt': jwt_token}

    def test_extra_fields_ignored(self):
        """
        Test that extra fields are ignored (not raising errors).
        """
        data_with_extra = {
            'jwt': ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' 'eyJzdWIiOiIxMjM0NTY3ODkwIn0.' 'dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U'),
            'extra_field': 'should be ignored',
        }
        serializer = WorkloadIdentityTokenResponseSerializer(data=data_with_extra)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        # Extra fields should not appear in validated_data
        assert 'extra_field' not in serializer.validated_data
