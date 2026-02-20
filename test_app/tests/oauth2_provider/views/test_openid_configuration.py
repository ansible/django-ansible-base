import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings

from ansible_base.lib.testing.util import feature_flag_enabled
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.django_db
def test_oauth2_provider_openid_configuration_valid_issuer_url(client):
    """
    As an anonymous user, accessing /o/.well-known/openid-configuration/ should include
    an issuer URL that ends with /o
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())
    with override_settings(OAUTH2_PROVIDER={'OIDC_ENABLED': True, 'OIDC_OIDC_RSA_PRIVATE_KEY': private_key}):
        with feature_flag_enabled('FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED'):
            url = get_relative_url("oauth2_provider:oidc-connect-discovery-info")
            response_json = client.get(url).json()
            assert response_json['issuer'].endswith(
                '/o'
            ), "issuer in discovery metadata is expected to end with /o and match the authorization root view, otherwise discovery will fail!"
