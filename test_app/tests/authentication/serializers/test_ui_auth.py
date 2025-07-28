from ansible_base.authentication.serializers.ui_auth import (
    PasswordAuthenticatorSerializer,
    SSOAuthenticatorSerializer,
    UIAuthResponseSerializer,
)


class TestPasswordAuthenticatorSerializer:
    def test_serializes_password_authenticator_data(self):
        """Test PasswordAuthenticatorSerializer serializes data correctly"""
        data = {'name': 'password_auth'}
        serializer = PasswordAuthenticatorSerializer(data)
        assert serializer.data == data

    def test_serializes_with_different_name(self):
        """Test PasswordAuthenticatorSerializer with different name"""
        data = {'name': 'local_password'}
        serializer = PasswordAuthenticatorSerializer(data)
        assert serializer.data == data


class TestSSOAuthenticatorSerializer:
    def test_serializes_sso_authenticator_data(self):
        """Test SSOAuthenticatorSerializer serializes data correctly"""
        data = {'name': 'sso_auth', 'login_url': 'https://example.com/login', 'type': 'saml'}
        serializer = SSOAuthenticatorSerializer(data)
        assert serializer.data == data

    def test_serializes_different_sso_types(self):
        """Test SSOAuthenticatorSerializer with different SSO types"""
        saml_data = {'name': 'saml_auth', 'login_url': 'https://example.com/saml', 'type': 'saml'}
        oidc_data = {'name': 'oidc_auth', 'login_url': 'https://example.com/oidc', 'type': 'oidc'}

        saml_serializer = SSOAuthenticatorSerializer(saml_data)
        oidc_serializer = SSOAuthenticatorSerializer(oidc_data)

        assert saml_serializer.data == saml_data
        assert oidc_serializer.data == oidc_data


class TestUIAuthResponseSerializer:
    def test_serializes_complete_auth_response(self):
        """Test UIAuthResponseSerializer serializes complete data correctly"""
        data = {
            'passwords': [{'name': 'password_auth'}],
            'ssos': [{'name': 'sso_auth', 'login_url': 'https://example.com/login', 'type': 'saml'}],
            'show_login_form': True,
            'login_redirect_override': 'https://example.com/redirect',
            'custom_login_info': 'Please login with your credentials',
            'custom_logo': 'data:image/gif;base64,R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs=',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data)
        assert serializer.data == data

    def test_serializes_minimal_auth_response(self):
        """Test UIAuthResponseSerializer serializes minimal data correctly"""
        data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data)
        assert serializer.data == data

    def test_serializes_multiple_password_authenticators(self):
        """Test UIAuthResponseSerializer with multiple password authenticators"""
        data = {
            'passwords': [{'name': 'password_auth_1'}, {'name': 'password_auth_2'}],
            'ssos': [],
            'show_login_form': True,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data)
        result = serializer.data
        assert len(result['passwords']) == 2
        assert result['passwords'][0] == {'name': 'password_auth_1'}
        assert result['passwords'][1] == {'name': 'password_auth_2'}

    def test_serializes_multiple_sso_authenticators(self):
        """Test UIAuthResponseSerializer with multiple SSO authenticators"""
        data = {
            'passwords': [],
            'ssos': [
                {'name': 'saml_auth', 'login_url': 'https://example.com/saml', 'type': 'saml'},
                {'name': 'oidc_auth', 'login_url': 'https://example.com/oidc', 'type': 'oidc'},
            ],
            'show_login_form': True,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data)
        result = serializer.data
        assert len(result['ssos']) == 2
        assert result['ssos'][0] == {'name': 'saml_auth', 'login_url': 'https://example.com/saml', 'type': 'saml'}
        assert result['ssos'][1] == {'name': 'oidc_auth', 'login_url': 'https://example.com/oidc', 'type': 'oidc'}

    def test_serializes_nested_authenticator_data(self):
        """Test UIAuthResponseSerializer correctly serializes nested authenticator data"""
        data = {
            'passwords': [{'name': 'local_auth'}, {'name': 'ldap_auth'}],
            'ssos': [
                {'name': 'google_sso', 'login_url': 'https://accounts.google.com/oauth', 'type': 'oidc'},
                {'name': 'okta_sso', 'login_url': 'https://company.okta.com/saml', 'type': 'saml'},
            ],
            'show_login_form': True,
            'login_redirect_override': '/dashboard',
            'custom_login_info': 'Use your company credentials',
            'custom_logo': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
            'managed_cloud_install': True,
        }
        serializer = UIAuthResponseSerializer(data)
        result = serializer.data

        # Verify top-level structure
        assert result == data

        # Verify nested data is properly serialized
        assert len(result['passwords']) == 2
        assert len(result['ssos']) == 2
        assert result['show_login_form'] is True
        assert result['managed_cloud_install'] is True

    def test_serializes_empty_authenticator_lists(self):
        """Test UIAuthResponseSerializer with empty authenticator lists"""
        data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data)
        result = serializer.data
        assert result['passwords'] == []
        assert result['ssos'] == []
        assert result['show_login_form'] is False

    def test_serializes_boolean_fields_correctly(self):
        """Test UIAuthResponseSerializer handles boolean fields correctly"""
        true_data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': True,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': True,
        }
        false_data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }

        true_serializer = UIAuthResponseSerializer(true_data)
        false_serializer = UIAuthResponseSerializer(false_data)

        assert true_serializer.data['show_login_form'] is True
        assert true_serializer.data['managed_cloud_install'] is True
        assert false_serializer.data['show_login_form'] is False
        assert false_serializer.data['managed_cloud_install'] is False

    def test_serializes_string_fields_correctly(self):
        """Test UIAuthResponseSerializer handles string fields correctly"""
        data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': 'https://example.com/custom-redirect',
            'custom_login_info': 'Welcome! Please sign in with your credentials.',
            'custom_logo': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAiIGhlaWdodD0iMTAiPjxyZWN0IHdpZHRoPSIxMCIgaGVpZ2h0PSIxMCIgZmlsbD0iYmx1ZSIvPjwvc3ZnPg==',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data)
        result = serializer.data

        assert result['login_redirect_override'] == 'https://example.com/custom-redirect'
        assert result['custom_login_info'] == 'Welcome! Please sign in with your credentials.'
        assert result['custom_logo'].startswith('data:image/svg+xml;base64,')

    def test_read_only_serializer_behavior(self):
        """Test that the serializer behaves as read-only (for documentation purposes)"""
        # This test documents that the serializer is read-only
        # Input validation is not performed since all fields are read_only=True
        data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }

        # When used as a response serializer (the intended use case)
        serializer = UIAuthResponseSerializer(data)
        assert serializer.data == data

        # When used with invalid input data (which would normally fail validation)
        # it still works because read_only fields are ignored during validation
        invalid_input = {'invalid_field': 'invalid_value'}
        input_serializer = UIAuthResponseSerializer(data=invalid_input)
        assert input_serializer.is_valid()  # Always valid since all fields are read_only
        assert input_serializer.validated_data == {}  # Empty since fields are read_only
