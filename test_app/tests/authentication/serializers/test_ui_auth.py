from ansible_base.authentication.serializers.ui_auth import (
    PasswordAuthenticatorSerializer,
    SSOAuthenticatorSerializer,
    UIAuthResponseSerializer,
)


class TestPasswordAuthenticatorSerializer:
    def test_valid_data(self):
        """Test PasswordAuthenticatorSerializer with valid data"""
        data = {'name': 'password_auth'}
        serializer = PasswordAuthenticatorSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.validated_data == data

    def test_missing_name(self):
        """Test PasswordAuthenticatorSerializer requires name field"""
        data = {}
        serializer = PasswordAuthenticatorSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_empty_name(self):
        """Test PasswordAuthenticatorSerializer handles empty name"""
        data = {'name': ''}
        serializer = PasswordAuthenticatorSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_name_type_coercion(self):
        """Test PasswordAuthenticatorSerializer coerces types to string"""
        data = {'name': 123}
        serializer = PasswordAuthenticatorSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.validated_data['name'] == '123'

    def test_name_invalid_type(self):
        """Test PasswordAuthenticatorSerializer with truly invalid type"""
        data = {'name': {'invalid': 'object'}}
        serializer = PasswordAuthenticatorSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors


class TestSSOAuthenticatorSerializer:
    def test_valid_data(self):
        """Test SSOAuthenticatorSerializer with valid data"""
        data = {'name': 'sso_auth', 'login_url': 'https://example.com/login', 'type': 'saml'}
        serializer = SSOAuthenticatorSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.validated_data == data

    def test_missing_required_fields(self):
        """Test SSOAuthenticatorSerializer requires all fields"""
        data = {}
        serializer = SSOAuthenticatorSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors
        assert 'login_url' in serializer.errors
        assert 'type' in serializer.errors

    def test_invalid_url(self):
        """Test SSOAuthenticatorSerializer validates URL format"""
        data = {'name': 'sso_auth', 'login_url': 'not_a_url', 'type': 'saml'}
        serializer = SSOAuthenticatorSerializer(data=data)
        assert not serializer.is_valid()
        assert 'login_url' in serializer.errors

    def test_empty_fields(self):
        """Test SSOAuthenticatorSerializer handles empty fields"""
        data = {'name': '', 'login_url': '', 'type': ''}
        serializer = SSOAuthenticatorSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors
        assert 'login_url' in serializer.errors

    def test_valid_url_formats(self):
        """Test various valid URL formats"""
        valid_urls = [
            'https://example.com/login',
            'http://localhost:8080/auth',
            'https://auth.company.com/saml/login?param=value',
        ]

        for url in valid_urls:
            data = {'name': 'sso_auth', 'login_url': url, 'type': 'saml'}
            serializer = SSOAuthenticatorSerializer(data=data)
            assert serializer.is_valid(), f"URL should be valid: {url}"


class TestUIAuthResponseSerializer:
    def test_valid_complete_data(self):
        """Test UIAuthResponseSerializer with complete valid data"""
        data = {
            'passwords': [{'name': 'password_auth'}],
            'ssos': [{'name': 'sso_auth', 'login_url': 'https://example.com/login', 'type': 'saml'}],
            'show_login_form': True,
            'login_redirect_override': 'https://example.com/redirect',
            'custom_login_info': 'Please login with your credentials',
            'custom_logo': 'data:image/gif;base64,R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs=',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.validated_data == data

    def test_valid_minimal_data(self):
        """Test UIAuthResponseSerializer with minimal required data"""
        data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.validated_data == data

    def test_missing_required_fields(self):
        """Test UIAuthResponseSerializer requires all fields"""
        data = {}
        serializer = UIAuthResponseSerializer(data=data)
        assert not serializer.is_valid()

        required_fields = ['passwords', 'ssos', 'show_login_form', 'login_redirect_override', 'custom_login_info', 'custom_logo', 'managed_cloud_install']
        for field in required_fields:
            assert field in serializer.errors

    def test_multiple_password_authenticators(self):
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
        serializer = UIAuthResponseSerializer(data=data)
        assert serializer.is_valid()
        assert len(serializer.validated_data['passwords']) == 2

    def test_multiple_sso_authenticators(self):
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
        serializer = UIAuthResponseSerializer(data=data)
        assert serializer.is_valid()
        assert len(serializer.validated_data['ssos']) == 2

    def test_invalid_nested_password_authenticator(self):
        """Test UIAuthResponseSerializer with invalid password authenticator"""
        data = {
            'passwords': [{'name': ''}],  # Invalid: empty name
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data=data)
        assert not serializer.is_valid()
        assert 'passwords' in serializer.errors

    def test_invalid_nested_sso_authenticator(self):
        """Test UIAuthResponseSerializer with invalid SSO authenticator"""
        data = {
            'passwords': [],
            'ssos': [{'name': 'sso_auth', 'login_url': 'invalid_url', 'type': 'saml'}],
            'show_login_form': False,
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data=data)
        assert not serializer.is_valid()
        assert 'ssos' in serializer.errors

    def test_boolean_field_validation(self):
        """Test boolean field validation"""
        data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': 'not_boolean',  # Invalid boolean
            'login_redirect_override': '',
            'custom_login_info': '',
            'custom_logo': '',
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data=data)
        assert not serializer.is_valid()
        assert 'show_login_form' in serializer.errors

    def test_string_field_allow_blank(self):
        """Test that string fields allow blank values"""
        data = {
            'passwords': [],
            'ssos': [],
            'show_login_form': False,
            'login_redirect_override': '',  # Should be allowed
            'custom_login_info': '',  # Should be allowed
            'custom_logo': '',  # Should be allowed
            'managed_cloud_install': False,
        }
        serializer = UIAuthResponseSerializer(data=data)
        assert serializer.is_valid()

    def test_field_types_validation(self):
        """Test field type validation for fields that don't allow coercion"""
        invalid_data = {
            'passwords': 'not_a_list',
            'ssos': 'not_a_list',
            'show_login_form': 'not_boolean',
            'login_redirect_override': '123',  # String that gets coerced
            'custom_login_info': '123',  # String that gets coerced
            'custom_logo': '123',  # String that gets coerced
            'managed_cloud_install': 'not_boolean',
        }
        serializer = UIAuthResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()

        # Only list and boolean fields should have validation errors
        # String fields accept coerced values
        expected_errors = ['passwords', 'ssos', 'show_login_form', 'managed_cloud_install']
        for field in expected_errors:
            assert field in serializer.errors

    def test_incompatible_types_validation(self):
        """Test field validation with truly incompatible types"""
        invalid_data = {
            'passwords': {'not': 'a_list'},
            'ssos': {'not': 'a_list'},
            'show_login_form': {'not': 'boolean'},
            'login_redirect_override': {'not': 'string'},
            'custom_login_info': {'not': 'string'},
            'custom_logo': {'not': 'string'},
            'managed_cloud_install': {'not': 'boolean'},
        }
        serializer = UIAuthResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()

        # All fields should have validation errors with dict inputs
        for field in invalid_data.keys():
            assert field in serializer.errors
