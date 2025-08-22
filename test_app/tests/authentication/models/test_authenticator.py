from unittest import mock

import pytest

from ansible_base.authentication.models import Authenticator


@pytest.mark.django_db
def test_authenticator_from_db(ldap_authenticator):
    ldap_auth = Authenticator.objects.first()
    # Validate that we got the proper password when loading the object the first time
    assert ldap_auth.configuration.get('BIND_PASSWORD', None) == 'securepassword'
    with mock.patch('ansible_base.authentication.models.authenticator.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        ldap_auth = Authenticator.objects.first()
        assert ldap_auth.configuration.get('BIND_PASSWORD', None) != 'securepassword'


@pytest.mark.django_db
def test_authenticator_order_on_create_update():
    """
    ensures that authenticator order = max(current order) + 1 for newly created authenticators
    and that order is generated correctly for new authenticators when there is an update in orders
    """
    auth_type = "ansible_base.authentication.authenticator_plugins.local"
    auth1 = Authenticator.objects.create(name='Authenticator 1', type=auth_type, order=11)
    auth2 = Authenticator.objects.create(name='Authenticator 2', type=auth_type)
    assert auth2.order == auth1.order + 1

    # update order of auth2
    auth2.order = 10
    auth2.save()

    auth3 = Authenticator.objects.create(name='Authenticator 3', type=auth_type)
    assert auth3.order == 12


@pytest.mark.django_db
def test_dupe_slug(ldap_authenticator):
    ldap_slug = ldap_authenticator.slug

    dupe = Authenticator()
    dupe.name = ldap_authenticator.name
    dupe.type = ldap_authenticator.type

    ldap_authenticator.name = "changed"
    ldap_authenticator.save()

    dupe.save()
    assert dupe.slug != ldap_slug, "authenticator slugs should be unique"


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins.oidc.OpenIdConnectAuth.JWT_ALGORITHMS", ["RS256", "HS256"])
@mock.patch("logging.getLogger")
def test_oidc_jwt_algorithms_auto_population(mock_get_logger):
    """Test that JWT algorithms are automatically populated when creating an OIDC authenticator"""
    from ansible_base.authentication.models import Authenticator

    # Mock the logger
    mock_logger = mock.MagicMock()
    mock_get_logger.return_value = mock_logger

    # Create OIDC authenticator without JWT_ALGORITHMS
    oidc_config = {
        "OIDC_ENDPOINT": "https://example.com",
        "VERIFY_SSL": True,
        "KEY": "test-client-id",
        "SECRET": "test-client-secret",
    }

    # Mock the OIDC plugin to return algorithms from .well-known
    with mock.patch("ansible_base.authentication.authenticator_plugins.oidc.AuthenticatorPlugin._get_jwt_algorithms") as mock_get_algs:
        mock_get_algs.return_value = ["RS256", "ES256"]

        oidc_auth = Authenticator.objects.create(name="Test OIDC", type="ansible_base.authentication.authenticator_plugins.oidc", configuration=oidc_config)

        # Verify that JWT_ALGORITHMS was populated
        assert "JWT_ALGORITHMS" in oidc_auth.configuration
        assert oidc_auth.configuration["JWT_ALGORITHMS"] == ["RS256", "ES256"]
        mock_logger.info.assert_called_with("Successfully populated JWT algorithms: ['RS256', 'ES256']")


@pytest.mark.django_db
def test_oidc_jwt_algorithms_not_populated_when_already_set():
    """Test that JWT algorithms are not modified when already configured"""
    from ansible_base.authentication.models import Authenticator

    # Create OIDC authenticator with JWT_ALGORITHMS already set
    oidc_config = {
        "OIDC_ENDPOINT": "https://example.com",
        "VERIFY_SSL": True,
        "KEY": "test-client-id",
        "SECRET": "test-client-secret",
        "JWT_ALGORITHMS": ["RS256"],  # Already configured
    }

    oidc_auth = Authenticator.objects.create(
        name="Test OIDC Configured", type="ansible_base.authentication.authenticator_plugins.oidc", configuration=oidc_config
    )

    # Verify that JWT_ALGORITHMS was not modified
    assert oidc_auth.configuration["JWT_ALGORITHMS"] == ["RS256"]


@pytest.mark.django_db
def test_non_oidc_authenticator_not_affected():
    """Test that non-OIDC authenticators are not affected by JWT algorithm logic"""
    from ansible_base.authentication.models import Authenticator

    # Create LDAP authenticator (non-OIDC)
    ldap_config = {
        "SERVER_URI": "ldap://example.com",
        "BIND_DN": "cn=admin,dc=example,dc=com",
        "BIND_PASSWORD": "password",
        "USER_SEARCH": ["ou=users,dc=example,dc=com", "SCOPE_SUBTREE", "(sAMAccountName=%(user)s)"],
    }

    ldap_auth = Authenticator.objects.create(name="Test LDAP", type="ansible_base.authentication.authenticator_plugins.ldap", configuration=ldap_config)

    # Verify that LDAP authenticator doesn't have JWT_ALGORITHMS
    assert "JWT_ALGORITHMS" not in ldap_auth.configuration


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins.oidc.OpenIdConnectAuth.JWT_ALGORITHMS", ["RS256", "HS256"])
@mock.patch("logging.getLogger")
def test_oidc_jwt_algorithms_auto_population_on_update(mock_get_logger):
    """Test that JWT algorithms are auto-populated when updating an OIDC authenticator"""
    from ansible_base.authentication.models import Authenticator

    # Mock the logger
    mock_logger = mock.MagicMock()
    mock_get_logger.return_value = mock_logger

    # Create OIDC authenticator without JWT_ALGORITHMS
    oidc_config = {
        "OIDC_ENDPOINT": "https://example.com",
        "VERIFY_SSL": True,
        "KEY": "test-client-id",
        "SECRET": "test-client-secret",
    }

    oidc_auth = Authenticator.objects.create(name="Test OIDC Update", type="ansible_base.authentication.authenticator_plugins.oidc", configuration=oidc_config)

    assert "JWT_ALGORITHMS" in oidc_auth.configuration
    assert oidc_auth.configuration["JWT_ALGORITHMS"] == ["RS256", "HS256"]
