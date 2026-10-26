from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.oauth_bearer import (
    AuthenticatorPlugin,
    OAuthBearerConfiguration,
    _local_oidc_issuer,
    apply_oidc_discovery,
    oidc_discovery_url,
    resolve_uid_from_claims,
)
from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin, get_authenticator_plugins
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.utils.response import get_relative_url

PLUGIN_TYPE = "ansible_base.authentication.authenticator_plugins.oauth_bearer"
DISCOVERY_MODULE = "ansible_base.authentication.authenticator_plugins.oauth_bearer"


def _discovery_document(**overrides):
    document = {
        "issuer": "https://login.example.com/tenant/v2.0",
        "jwks_uri": "https://login.example.com/tenant/discovery/v2.0/keys",
        "userinfo_endpoint": "https://login.example.com/tenant/openid/userinfo",
    }
    document.update(overrides)
    return document


def _mock_requests_get(payload, expected_verify=None, status_code=200, expected_timeout=None, text=None):
    """Return a side_effect for requests.get that yields a JSON response."""

    def _get(url, headers=None, timeout=None, verify=True):
        if expected_verify is not None:
            assert verify is expected_verify
        if expected_timeout is not None:
            assert timeout == expected_timeout
        response = MagicMock()
        response.status_code = status_code
        if isinstance(payload, (bytes, bytearray)):
            response.text = text if text is not None else payload.decode(errors="replace")
            response.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", response.text, 0)
        else:
            response.json.return_value = payload
            response.text = text if text is not None else ("" if payload is None else str(payload))
        return response

    return _get


def _authenticator_payload(name, configuration, enabled=True):
    return {
        "name": name,
        "enabled": enabled,
        "create_objects": True,
        "remove_users": True,
        "type": PLUGIN_TYPE,
        "configuration": configuration,
    }


@pytest.mark.parametrize(
    ("oauth2_provider", "expected"),
    [
        ({"OIDC_ISS_ENDPOINT": " https://gateway.example.com/o "}, "https://gateway.example.com/o"),
        ({"OIDC_ISS_ENDPOINT": ""}, None),
        ({"OIDC_ISS_ENDPOINT": None}, None),
        ({}, None),
        ([], None),
    ],
)
@override_settings(INSTALLED_APPS=["ansible_base.oauth2_provider"])
def test_local_oidc_issuer_handles_provider_configuration(oauth2_provider, expected):
    """Only a non-empty string local issuer reserves an OAuth Bearer issuer URL."""
    with patch(f"{DISCOVERY_MODULE}.get_setting", return_value=oauth2_provider):
        assert _local_oidc_issuer() == expected


@override_settings(INSTALLED_APPS=[])
def test_local_oidc_issuer_is_unset_without_the_optional_oauth2_provider():
    """Authentication-only installations have no local issuer to reserve."""
    assert _local_oidc_issuer() is None


@pytest.mark.django_db
def test_oauth_bearer_plugin_registered():
    assert PLUGIN_TYPE in get_authenticator_plugins()
    plugin = get_authenticator_plugin(PLUGIN_TYPE)
    assert isinstance(plugin, AuthenticatorPlugin)
    assert plugin.type == "oauth_bearer"
    assert plugin.category == "api_auth"
    assert plugin.get_login_url(None) is None


@pytest.mark.django_db
def test_oauth_bearer_create_update_delete_via_api(admin_api_client, oauth_bearer_configuration):
    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=_authenticator_payload("Entra OAuth Bearer", oauth_bearer_configuration), format="json")
    assert response.status_code == 201, response.data
    authenticator_id = response.data["id"]
    authenticator = Authenticator.objects.get(id=authenticator_id)
    assert authenticator.category == "api_auth"
    assert response.data["configuration"]["CLAIM_LIST"] == ["email", "azp"]
    assert response.data["configuration"]["ISSUER_URL"] == oauth_bearer_configuration["ISSUER_URL"]

    detail_url = get_relative_url("authenticator-detail", kwargs={"pk": authenticator_id})
    updated_config = deepcopy(oauth_bearer_configuration)
    updated_config["AUDIENCE"] = "api://updated"
    updated_config["CLAIM_LIST"] = ["preferred_username", "client_id"]
    response = admin_api_client.patch(detail_url, data={"configuration": updated_config}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["configuration"]["AUDIENCE"] == "api://updated"
    assert response.data["configuration"]["CLAIM_LIST"] == ["preferred_username", "client_id"]

    response = admin_api_client.delete(detail_url)
    assert response.status_code == 204
    assert not Authenticator.objects.filter(id=authenticator_id).exists()


@pytest.mark.django_db
def test_oauth_bearer_allows_https_container_service_jwks_url(admin_api_client, oauth_bearer_configuration):
    """HTTPS JWKS endpoints may use a single-label container service hostname."""
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = "https://keycloak:8443/auth/realms/gateway/protocol/openid-connect/certs"

    response = admin_api_client.post(
        get_relative_url("authenticator-list"),
        data=_authenticator_payload("Container Keycloak", config),
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["configuration"]["JWKS_URI"] == config["JWKS_URI"]


@pytest.mark.django_db
def test_oauth_bearer_discovery_allows_https_container_service_urls(admin_api_client, oauth_bearer_configuration):
    """Discovery accepts HTTPS endpoints served through a container service hostname."""
    config = deepcopy(oauth_bearer_configuration)
    config.update(
        {
            "JWKS_URI": "",
            "OIDC_ENDPOINT": "https://keycloak:8443/auth/realms/gateway",
        }
    )
    jwks_uri = "https://keycloak:8443/auth/realms/gateway/protocol/openid-connect/certs"

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(_discovery_document(jwks_uri=jwks_uri))):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovered Container Keycloak", config),
            format="json",
        )

    assert response.status_code == 201, response.data
    assert response.data["configuration"]["JWKS_URI"] == jwks_uri


@pytest.mark.django_db
def test_oauth_bearer_multiple_providers(admin_api_client, oauth_bearer_configuration):
    url = get_relative_url("authenticator-list")
    first = deepcopy(oauth_bearer_configuration)
    second = deepcopy(oauth_bearer_configuration)
    second["ISSUER_URL"] = "https://keycloak.example.com/realms/aap"
    second["JWKS_URI"] = "https://keycloak.example.com/realms/aap/protocol/openid-connect/certs"
    second["CLAIM_LIST"] = ["preferred_username", "client_id"]

    response_one = admin_api_client.post(url, data=_authenticator_payload("Provider One", first), format="json")
    response_two = admin_api_client.post(url, data=_authenticator_payload("Provider Two", second), format="json")
    assert response_one.status_code == 201, response_one.data
    assert response_two.status_code == 201, response_two.data
    assert response_one.data["id"] != response_two.data["id"]

    response = admin_api_client.get(url)
    assert response.status_code == 200
    names = {item["name"] for item in response.data["results"]}
    assert {"Provider One", "Provider Two"}.issubset(names)


@pytest.mark.django_db
@override_settings(OAUTH2_PROVIDER={"OIDC_ISS_ENDPOINT": "https://gateway.example.com/o"})
def test_oauth_bearer_rejects_the_local_oidc_issuer(admin_api_client, oauth_bearer_configuration):
    """DAB reserves its own optional OIDC issuer for local token handling."""
    config = deepcopy(oauth_bearer_configuration)
    config["ISSUER_URL"] = "https://gateway.example.com/o"
    response = admin_api_client.post(
        get_relative_url("authenticator-list"),
        data=_authenticator_payload("Local OIDC Collision", config),
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "ISSUER_URL" in response.data.get("configuration", response.data)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "mutation,expected_fields",
    [
        (lambda cfg: cfg.pop("ISSUER_URL"), ["ISSUER_URL"]),
        (lambda cfg: cfg.pop("AUDIENCE"), ["AUDIENCE"]),
        (lambda cfg: cfg.update({"AUDIENCE": ""}), ["AUDIENCE"]),
        (lambda cfg: cfg.update({"CLAIM_LIST": []}), ["CLAIM_LIST"]),
        (lambda cfg: cfg.pop("CLAIM_LIST"), ["CLAIM_LIST"]),
        (lambda cfg: cfg.update({"JWKS_URI": "", "OIDC_ENDPOINT": ""}), ["JWKS_URI", "OIDC_ENDPOINT"]),
        (lambda cfg: cfg.update({"JWKS_URI": None, "OIDC_ENDPOINT": None}), ["JWKS_URI", "OIDC_ENDPOINT"]),
        (lambda cfg: cfg.update({"ALLOWED_ALGORITHMS": []}), ["ALLOWED_ALGORITHMS"]),
        (lambda cfg: cfg.update({"ALLOWED_ALGORITHMS": ["NOT_A_REAL_ALG"]}), ["ALLOWED_ALGORITHMS"]),
        (lambda cfg: cfg.update({"ALLOWED_ALGORITHMS": ["HS256"]}), ["ALLOWED_ALGORITHMS"]),
        (lambda cfg: cfg.update({"ALLOWED_ALGORITHMS": ["none"]}), ["ALLOWED_ALGORITHMS"]),
        (lambda cfg: cfg.update({"JWKS_URL_TIMEOUT": 0}), ["JWKS_URL_TIMEOUT"]),
        (lambda cfg: cfg.update({"JWKS_URL_TIMEOUT": 301}), ["JWKS_URL_TIMEOUT"]),
        (lambda cfg: cfg.update({"JWT_CLOCK_SKEW_TOLERANCE_SECONDS": -1}), ["JWT_CLOCK_SKEW_TOLERANCE_SECONDS"]),
        (lambda cfg: cfg.update({"JWT_CLOCK_SKEW_TOLERANCE_SECONDS": 301}), ["JWT_CLOCK_SKEW_TOLERANCE_SECONDS"]),
        (lambda cfg: cfg.update({"JWKS_CACHE_TIMEOUT": 30}), ["JWKS_CACHE_TIMEOUT"]),
        (lambda cfg: cfg.update({"JWKS_URI": "http://provider.example.com/keys"}), ["JWKS_URI"]),
        (lambda cfg: cfg.update({"OIDC_ENDPOINT": "http://provider.example.com", "JWKS_URI": ""}), ["OIDC_ENDPOINT"]),
        (lambda cfg: cfg.update({"CLAIM_LIST": ["email", ""]}), ["CLAIM_LIST"]),
        (lambda cfg: cfg.update({"CLAIM_LIST": ["email", 123]}), ["CLAIM_LIST"]),
        (lambda cfg: cfg.update({"not_a_real_field": "nope"}), ["not_a_real_field"]),
    ],
)
def test_oauth_bearer_invalid_configuration(admin_api_client, oauth_bearer_configuration, mutation, expected_fields):
    config = deepcopy(oauth_bearer_configuration)
    mutation(config)
    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=_authenticator_payload("Invalid OAuth Bearer", config), format="json")
    assert response.status_code == 400, response.data
    for field in expected_fields:
        assert field in response.data or field in response.data.get("configuration", response.data)


@pytest.mark.django_db
def test_oauth_bearer_enable_disable_toggle_preserves_configuration(admin_api_client, oauth_bearer_configuration):
    """Disable/enable must preserve configuration without requiring recreate."""
    url = get_relative_url("authenticator-list")
    create_response = admin_api_client.post(
        url,
        data=_authenticator_payload("Toggle OAuth Bearer", oauth_bearer_configuration, enabled=True),
        format="json",
    )
    assert create_response.status_code == 201, create_response.data
    authenticator_id = create_response.data["id"]
    detail_url = get_relative_url("authenticator-detail", kwargs={"pk": authenticator_id})

    disable_response = admin_api_client.patch(detail_url, data={"enabled": False}, format="json")
    assert disable_response.status_code == 200, disable_response.data
    assert disable_response.data["enabled"] is False
    assert disable_response.data["configuration"]["ISSUER_URL"] == oauth_bearer_configuration["ISSUER_URL"]
    assert disable_response.data["configuration"]["CLAIM_LIST"] == ["email", "azp"]

    get_response = admin_api_client.get(detail_url)
    assert get_response.status_code == 200
    assert get_response.data["enabled"] is False
    assert get_response.data["configuration"]["JWKS_URI"] == oauth_bearer_configuration["JWKS_URI"]

    enable_response = admin_api_client.patch(detail_url, data={"enabled": True}, format="json")
    assert enable_response.status_code == 200, enable_response.data
    assert enable_response.data["enabled"] is True
    assert enable_response.data["configuration"]["CLAIM_LIST"] == ["email", "azp"]


@pytest.mark.parametrize(
    "claims,claim_list,expected",
    [
        ({"email": "user@example.com", "azp": "sp-app"}, ["email", "azp"], "user@example.com"),
        ({"azp": "sp-app"}, ["email", "azp"], "sp-app"),
        ({"email": "", "azp": "sp-app"}, ["email", "azp"], "sp-app"),
        ({"email": "   ", "client_id": "svc-1"}, ["email", "client_id"], "svc-1"),
        ({"preferred_username": "alice", "sub": "abc"}, ["preferred_username", "sub"], "alice"),
        ({"sub": "abc"}, ["email", "azp"], None),
        ({}, ["email", "azp"], None),
        ({"email": "user@example.com"}, [], None),
        ({"email": None, "azp": "sp-app"}, ["email", "azp"], "sp-app"),
        # Service-principal-only ordering
        ({"email": "user@example.com", "azp": "sp-app"}, ["azp", "email"], "sp-app"),
        ({"client_id": "svc-client"}, ["client_id", "email"], "svc-client"),
        ({"upn": "user@corp.example"}, ["upn", "email"], "user@corp.example"),
        # Non-scalar claim values are skipped (not stringified)
        ({"email": ["user@example.com"], "azp": "sp-app"}, ["email", "azp"], "sp-app"),
        ({"email": {"value": "user@example.com"}, "azp": "sp-app"}, ["email", "azp"], "sp-app"),
        ({"email": ["user@example.com"]}, ["email"], None),
        # Integers are accepted; bool/float are not (bool is an int subclass)
        ({"sub": 12345}, ["sub"], "12345"),
        ({"sub": True, "azp": "sp-app"}, ["sub", "azp"], "sp-app"),
        ({"sub": 1.5, "azp": "sp-app"}, ["sub", "azp"], "sp-app"),
        ({"sub": False}, ["sub"], None),
    ],
)
def test_claim_list_identity_resolution(claims, claim_list, expected):
    assert resolve_uid_from_claims(claims, claim_list) == expected


@pytest.mark.django_db
def test_oauth_bearer_validate_accumulates_object_errors(admin_api_client, oauth_bearer_configuration):
    """Endpoint-pair and CLAIM_LIST errors should be returned together."""
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = ""
    config["CLAIM_LIST"] = ["email", ""]
    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=_authenticator_payload("Accumulated Errors", config), format="json")
    assert response.status_code == 400, response.data
    error_payload = response.data.get("configuration", response.data)
    assert "JWKS_URI" in error_payload or "JWKS_URI" in response.data
    assert "OIDC_ENDPOINT" in error_payload or "OIDC_ENDPOINT" in response.data
    assert "CLAIM_LIST" in error_payload or "CLAIM_LIST" in response.data


@pytest.mark.django_db
def test_claim_list_order_preserved_via_api(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["CLAIM_LIST"] = ["azp", "email", "preferred_username"]
    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=_authenticator_payload("Ordered Claims", config), format="json")
    assert response.status_code == 201, response.data
    assert response.data["configuration"]["CLAIM_LIST"] == ["azp", "email", "preferred_username"]


@pytest.mark.django_db
def test_oauth_bearer_schema_has_no_separate_user_service_claim_fields():
    schema_names = {field["name"] for field in OAuthBearerConfiguration().get_configuration_schema()}
    assert "CLAIM_LIST" in schema_names
    assert "USERNAME_CLAIM" not in schema_names
    assert "CLIENT_ID_CLAIM" not in schema_names
    assert "USER_CLAIM" not in schema_names
    assert "SERVICE_CLAIM" not in schema_names


@pytest.mark.django_db
def test_get_default_attributes_uses_configured_claims(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    assert plugin.get_default_attributes() == ["email", "azp", "groups"]

    oauth_bearer_authenticator.configuration = {
        **oauth_bearer_authenticator.configuration,
        "CLAIM_LIST": ["preferred_username", "client_id"],
        "GROUPS_CLAIM": "Group",
    }
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    assert plugin.get_default_attributes() == ["preferred_username", "client_id", "Group"]

    unconfigured = AuthenticatorPlugin()
    assert "email" in unconfigured.get_default_attributes()
    assert "groups" in unconfigured.get_default_attributes()


@pytest.mark.django_db
def test_oauth_bearer_existing_authenticator_compatibility(admin_api_client, local_authenticator, oidc_authenticator, oauth_bearer_configuration):
    """Creating oauth_bearer must not disturb existing authenticator types."""
    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=_authenticator_payload("Compat OAuth Bearer", oauth_bearer_configuration), format="json")
    assert response.status_code == 201, response.data

    list_response = admin_api_client.get(url)
    assert list_response.status_code == 200
    types = {item["type"] for item in list_response.data["results"]}
    assert PLUGIN_TYPE in types
    assert local_authenticator.type in types
    assert oidc_authenticator.type in types

    local_detail = get_relative_url("authenticator-detail", kwargs={"pk": local_authenticator.id})
    local_response = admin_api_client.get(local_detail)
    assert local_response.status_code == 200
    assert local_response.data["enabled"] is True


@pytest.mark.django_db
def test_api_auth_not_presented_as_login_choice(oauth_bearer_authenticator, local_authenticator):
    """api_auth authenticators must not appear as password or SSO login choices."""
    from ansible_base.authentication.views.ui_auth import generate_ui_auth_data

    result = generate_ui_auth_data()
    password_names = {item.get("name") for item in result["passwords"]}
    sso_names = {item.get("name") for item in result["ssos"]}
    assert oauth_bearer_authenticator.name not in password_names
    assert oauth_bearer_authenticator.name not in sso_names
    assert local_authenticator.name in password_names


@pytest.mark.django_db
def test_oidc_discovery_populates_jwks_and_userinfo(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["USERINFO_URL"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    document = _discovery_document()

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(document)) as mock_get:
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovered OAuth Bearer", config),
            format="json",
        )

    assert response.status_code == 201, response.data
    assert response.data["configuration"]["JWKS_URI"] == document["jwks_uri"]
    assert response.data["configuration"]["USERINFO_URL"] == document["userinfo_endpoint"]
    assert response.data["configuration"]["OIDC_ENDPOINT"] == config["OIDC_ENDPOINT"]
    assert mock_get.call_args.args[0] == oidc_discovery_url(config["OIDC_ENDPOINT"])


@pytest.mark.django_db
def test_oidc_discovery_missing_userinfo_still_populates_jwks(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["USERINFO_URL"] = "https://manual.example.com/userinfo"
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    document = _discovery_document()
    document.pop("userinfo_endpoint")

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(document)):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Without UserInfo", config),
            format="json",
        )

    assert response.status_code == 201, response.data
    assert response.data["configuration"]["JWKS_URI"] == document["jwks_uri"]
    # Manual USERINFO_URL is preserved when discovery omits userinfo_endpoint.
    assert response.data["configuration"]["USERINFO_URL"] == config["USERINFO_URL"]


@pytest.mark.django_db
def test_oidc_discovery_takes_precedence_over_manual_jwks(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = "https://manual.example.com/keys"
    config["USERINFO_URL"] = "https://manual.example.com/userinfo"
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    document = _discovery_document(
        jwks_uri="https://discovered.example.com/keys",
        userinfo_endpoint="https://discovered.example.com/userinfo",
    )

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(document)):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Precedence", config),
            format="json",
        )

    assert response.status_code == 201, response.data
    assert response.data["configuration"]["JWKS_URI"] == "https://discovered.example.com/keys"
    assert response.data["configuration"]["USERINFO_URL"] == "https://discovered.example.com/userinfo"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "side_effect,expected_substring",
    [
        (requests.exceptions.ConnectionError("connection refused"), "Unable to reach"),
        (_mock_requests_get({"jwks_uri": "https://x"}, status_code=500), "HTTP 500"),
        (_mock_requests_get({"jwks_uri": "https://x"}, status_code=204), "HTTP 204"),
    ],
)
def test_oidc_discovery_network_errors(admin_api_client, oauth_bearer_configuration, side_effect, expected_substring):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=side_effect):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Network Error", config),
            format="json",
        )

    assert response.status_code == 400, response.data
    error_payload = response.data.get("configuration", response.data)
    assert "OIDC_ENDPOINT" in error_payload or "OIDC_ENDPOINT" in response.data
    message = str(error_payload.get("OIDC_ENDPOINT") or response.data.get("OIDC_ENDPOINT"))
    assert expected_substring in message


@pytest.mark.django_db
def test_oidc_discovery_invalid_json(admin_api_client, oauth_bearer_configuration, caplog):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"

    with caplog.at_level("DEBUG", logger=DISCOVERY_MODULE):
        with patch(
            f"{DISCOVERY_MODULE}.requests.get",
            side_effect=_mock_requests_get(b"not-json{", text="not-json{"),
        ):
            response = admin_api_client.post(
                get_relative_url("authenticator-list"),
                data=_authenticator_payload("Discovery Invalid JSON", config),
                format="json",
            )

    assert response.status_code == 400, response.data
    error_payload = response.data.get("configuration", response.data)
    message = str(error_payload.get("OIDC_ENDPOINT") or response.data.get("OIDC_ENDPOINT"))
    assert "not valid JSON" in message
    assert "Unable to reach" not in message
    assert any("invalid JSON" in record.message and "not-json{" in record.message for record in caplog.records)


@pytest.mark.django_db
def test_oidc_discovery_missing_jwks_uri(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    document = _discovery_document()
    document.pop("jwks_uri")

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(document)):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Missing JWKS", config),
            format="json",
        )

    assert response.status_code == 400, response.data
    error_payload = response.data.get("configuration", response.data)
    assert "OIDC_ENDPOINT" in error_payload or "OIDC_ENDPOINT" in response.data


@pytest.mark.django_db
def test_oidc_discovery_respects_verify_ssl_false(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    config["VERIFY_SSL"] = False
    document = _discovery_document()

    with patch(
        f"{DISCOVERY_MODULE}.requests.get",
        side_effect=_mock_requests_get(document, expected_verify=False),
    ):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Insecure SSL", config),
            format="json",
        )

    assert response.status_code == 201, response.data
    assert response.data["configuration"]["JWKS_URI"] == document["jwks_uri"]


@pytest.mark.django_db
def test_oidc_discovery_timeout(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=requests.exceptions.Timeout("timed out")):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Timeout", config),
            format="json",
        )

    assert response.status_code == 400, response.data
    error_payload = response.data.get("configuration", response.data)
    message = str(error_payload.get("OIDC_ENDPOINT") or response.data.get("OIDC_ENDPOINT"))
    assert "timed out" in message.lower()


@pytest.mark.django_db
def test_oidc_discovery_non_object_json(admin_api_client, oauth_bearer_configuration, caplog):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"

    with caplog.at_level("DEBUG", logger=DISCOVERY_MODULE):
        with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get([{"jwks_uri": "x"}])):
            response = admin_api_client.post(
                get_relative_url("authenticator-list"),
                data=_authenticator_payload("Discovery Non Object JSON", config),
                format="json",
            )

    assert response.status_code == 400, response.data
    error_payload = response.data.get("configuration", response.data)
    message = str(error_payload.get("OIDC_ENDPOINT") or response.data.get("OIDC_ENDPOINT"))
    assert "JSON object" in message
    assert any("type=list" in record.message for record in caplog.records)


@pytest.mark.django_db
def test_oidc_discovery_rejects_invalid_discovered_jwks_uri(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    document = _discovery_document(jwks_uri="not a url")

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(document)):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Invalid JWKS URL", config),
            format="json",
        )

    assert response.status_code == 400, response.data
    error_payload = response.data.get("configuration", response.data)
    message = str(error_payload.get("OIDC_ENDPOINT") or response.data.get("OIDC_ENDPOINT"))
    assert "invalid jwks_uri" in message


@pytest.mark.django_db
def test_oidc_discovery_overwrites_manual_values_on_update(admin_api_client, oauth_bearer_configuration):
    """While OIDC_ENDPOINT remains set, every save re-runs discovery and overwrites JWKS/UserInfo."""
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    initial_document = _discovery_document(
        jwks_uri="https://discovered.example.com/keys-v1",
        userinfo_endpoint="https://discovered.example.com/userinfo-v1",
    )

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(initial_document)):
        create_response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Ownership", config),
            format="json",
        )
    assert create_response.status_code == 201, create_response.data
    authenticator_id = create_response.data["id"]

    updated_config = deepcopy(create_response.data["configuration"])
    updated_config["JWKS_URI"] = "https://manual.example.com/keys"
    updated_config["USERINFO_URL"] = "https://manual.example.com/userinfo"
    refreshed_document = _discovery_document(
        jwks_uri="https://discovered.example.com/keys-v2",
        userinfo_endpoint="https://discovered.example.com/userinfo-v2",
    )

    with patch(f"{DISCOVERY_MODULE}.requests.get", side_effect=_mock_requests_get(refreshed_document)):
        update_response = admin_api_client.patch(
            get_relative_url("authenticator-detail", kwargs={"pk": authenticator_id}),
            data={"configuration": updated_config},
            format="json",
        )

    assert update_response.status_code == 200, update_response.data
    assert update_response.data["configuration"]["JWKS_URI"] == "https://discovered.example.com/keys-v2"
    assert update_response.data["configuration"]["USERINFO_URL"] == "https://discovered.example.com/userinfo-v2"


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_OAUTH_BEARER_DISCOVERY_TIMEOUT=12)
def test_oidc_discovery_uses_configured_timeout(admin_api_client, oauth_bearer_configuration):
    config = deepcopy(oauth_bearer_configuration)
    config["JWKS_URI"] = ""
    config["OIDC_ENDPOINT"] = "https://login.example.com/tenant/v2.0"
    document = _discovery_document()

    with patch(
        f"{DISCOVERY_MODULE}.requests.get",
        side_effect=_mock_requests_get(document, expected_timeout=12),
    ):
        response = admin_api_client.post(
            get_relative_url("authenticator-list"),
            data=_authenticator_payload("Discovery Timeout Setting", config),
            format="json",
        )

    assert response.status_code == 201, response.data


def test_apply_oidc_discovery_noop_without_endpoint():
    attrs = {"JWKS_URI": "https://manual.example.com/keys", "OIDC_ENDPOINT": ""}
    assert apply_oidc_discovery(attrs) is attrs
    assert attrs["JWKS_URI"] == "https://manual.example.com/keys"


def test_apply_oidc_discovery_rejects_empty_jwks_uri():
    with patch(f"{DISCOVERY_MODULE}.fetch_oidc_discovery", return_value={"jwks_uri": "   "}):
        with pytest.raises(ValidationError) as exc_info:
            apply_oidc_discovery({"OIDC_ENDPOINT": "https://login.example.com/tenant/v2.0"})
    assert "OIDC_ENDPOINT" in exc_info.value.detail
