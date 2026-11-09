"""RBAC for external-OAuth users: permissions come from AAP role assignments, never from JWT claims."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model

from ansible_base.authentication.bearer_authentication import (
    get_api_authentication_backends,
)
from ansible_base.lib.utils.response import get_relative_url
from test_app.models import Inventory, Organization

PLUGIN = "ansible_base.authentication.authenticator_plugins.oauth_bearer"


def _claims(configuration, email=None, **extra):
    """Build a token's claims; ``email=None`` gives a client-credentials-shaped token with no human identity."""
    claims = {
        "iss": configuration["ISSUER_URL"],
        "aud": configuration["AUDIENCE"],
        "scope": "read",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }
    if email is not None:
        claims["sub"] = f"subject-{email}"
        claims["email"] = email
    claims.update(extra)
    return claims


def _keep_local_assignments(authenticator):
    """Turn off claim-driven reconciliation, which would otherwise wipe every local role assignment on each request.

    With remove_users=True (the fixture default) the provider owns the user's roles and
    purges anything assigned locally. AAP grants roles through its own RBAC API, so these
    tests run the provider in the mode where those grants survive authentication.
    """
    authenticator.remove_users = False
    authenticator.save()
    return authenticator


def _external_request(client, authenticator, email, url, **extra):
    """Make one request through the real dispatcher with a signed-token stand-in, as an external user would."""
    claims = _claims(authenticator.configuration, email, **extra)
    get_api_authentication_backends.cache_clear()
    try:
        with ExitStack() as stack:
            jwk_client = stack.enter_context(patch(f"{PLUGIN}.CachedJWKClient"))
            stack.enter_context(patch(f"{PLUGIN}.decode", side_effect=lambda _token, **_kwargs: claims))
            jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
            return client.get(url, headers={"Authorization": "Bearer external-token"})
    finally:
        get_api_authentication_backends.cache_clear()


def _login(client, authenticator, email, **extra):
    return _external_request(client, authenticator, email, get_relative_url("user-me"), **extra)


def _user_for(login_response):
    return get_user_model().objects.get(username=login_response.data["username"])


def _inventory_ids(client, authenticator, email, **extra):
    response = _external_request(client, authenticator, email, get_relative_url("inventory-list"), **extra)
    assert response.status_code == 200
    return [row["id"] for row in response.data["results"]]


@pytest.mark.django_db
def test_external_user_read_access_follows_the_assigned_role(oauth_bearer_authenticator, inventory, org_inv_rd, unauthenticated_api_client):
    """A JIT-provisioned external user sees only what its AAP RBAC assignment allows (TC-1 items 6 and 7)."""
    _keep_local_assignments(oauth_bearer_authenticator)

    login = _login(unauthenticated_api_client, oauth_bearer_authenticator, "auditor@example.com")
    assert login.status_code == 200

    assert (
        _inventory_ids(
            unauthenticated_api_client,
            oauth_bearer_authenticator,
            "auditor@example.com",
        )
        == []
    )

    org_inv_rd.give_permission(_user_for(login), inventory.organization)

    assert _inventory_ids(unauthenticated_api_client, oauth_bearer_authenticator, "auditor@example.com") == [inventory.id]


@pytest.mark.django_db
def test_jwt_roles_claim_grants_nothing_without_an_aap_assignment(oauth_bearer_authenticator, inventory, org_inv_rd, unauthenticated_api_client):
    """A roles[] claim in the JWT grants no RBAC; only AAP assignments do (TC-1 item 8).

    The same user sees the inventory once given an AAP permission. That positive
    control is what makes the empty result meaningful: without it the test could
    pass on a broken harness rather than on the claim being ignored.
    """
    _keep_local_assignments(oauth_bearer_authenticator)

    login = _login(
        unauthenticated_api_client,
        oauth_bearer_authenticator,
        "claim-admin@example.com",
        roles=["admin"],
    )
    assert login.status_code == 200

    user = _user_for(login)
    assert not user.is_superuser
    assert (
        _inventory_ids(
            unauthenticated_api_client,
            oauth_bearer_authenticator,
            "claim-admin@example.com",
            roles=["admin"],
        )
        == []
    )

    org_inv_rd.give_permission(user, inventory.organization)
    assert _inventory_ids(
        unauthenticated_api_client,
        oauth_bearer_authenticator,
        "claim-admin@example.com",
        roles=["admin"],
    ) == [inventory.id]


@pytest.mark.django_db
def test_human_user_and_service_principal_permissions_stay_independent(oauth_bearer_authenticator, inventory, org_inv_rd, unauthenticated_api_client):
    """Grants to a human never bleed to a service-principal token, and vice versa (TC-1 item 14).

    The service token is client-credentials-shaped: a client_id subject and no email,
    so it maps to its own local user rather than a second named human.
    """
    _keep_local_assignments(oauth_bearer_authenticator)
    # Real provider configs key on the token subject (Entra: oid, Keycloak: sub), which
    # is what lets a client-credentials token with no email map to its own user.
    oauth_bearer_authenticator.configuration = {**oauth_bearer_authenticator.configuration, "ID_KEY": "sub"}
    oauth_bearer_authenticator.save()
    service_organization = Organization.objects.create(name="Service Principal Organization")
    service_inventory = Inventory.objects.create(name="service-inventory", organization=service_organization)

    service_claims = {"sub": "aap-service-client", "azp": "aap-service-client", "client_id": "aap-service-client"}
    human_login = _login(unauthenticated_api_client, oauth_bearer_authenticator, "human@example.com")
    service_login = _login(unauthenticated_api_client, oauth_bearer_authenticator, None, **service_claims)
    assert human_login.status_code == 200 and service_login.status_code == 200

    human_user = _user_for(human_login)
    service_user = _user_for(service_login)
    assert human_user.pk != service_user.pk

    org_inv_rd.give_permission(human_user, inventory.organization)
    org_inv_rd.give_permission(service_user, service_organization)

    assert _inventory_ids(unauthenticated_api_client, oauth_bearer_authenticator, "human@example.com") == [inventory.id]
    assert _inventory_ids(
        unauthenticated_api_client,
        oauth_bearer_authenticator,
        None,
        **service_claims,
    ) == [service_inventory.id]
