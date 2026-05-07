from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from oauthlib.common import generate_token

from ansible_base.activitystream.models import Entry
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2AccessToken


@pytest.fixture
def only_oauth_scope_permission(settings):
    from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

    with mock.patch("rest_framework.views.APIView.permission_classes", [OAuth2ScopePermission]):
        yield


def test_oauth2_bearer_get_user_correct(unauthenticated_api_client, oauth2_admin_access_token):
    """
    Perform a GET with a bearer token and ensure the authed user is correct.
    """
    url = get_relative_url("user-me")
    response = unauthenticated_api_client.get(
        url,
        headers={"Authorization": f"Bearer {oauth2_admin_access_token[1]}"},
    )
    assert response.status_code == 200
    assert response.data["username"] == oauth2_admin_access_token[0].user.username


@pytest.mark.parametrize("prefix", ["Bearer", "Token", "bearer", "token", "BEARER", "TOKEN"])
def test_oauth2_token_prefix_variants(unauthenticated_api_client, oauth2_admin_access_token, animal, prefix):
    """
    GET an animal with Bearer or Token prefix (AAP-68669).
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    response = unauthenticated_api_client.get(
        url,
        headers={"Authorization": f"{prefix} {oauth2_admin_access_token[1]}"},
    )
    assert response.status_code == 200
    assert response.data["name"] == animal.name


@pytest.mark.parametrize("prefix", ["Junk", "Basic", "Digest"])
def test_oauth2_token_invalid_prefix_rejected(unauthenticated_api_client, oauth2_admin_access_token, animal, prefix):
    """
    Verify that valid tokens with unsupported prefixes are rejected (AAP-68669).
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    response = unauthenticated_api_client.get(
        url,
        headers={"Authorization": f"{prefix} {oauth2_admin_access_token[1]}"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "token, expected",
    [
        ("fixture", 200),
        ("bad", 401),
    ],
)
def test_oauth2_bearer_get(unauthenticated_api_client, oauth2_admin_access_token, animal, token, expected):
    """
    GET an animal with a bearer token.
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1] if token == "fixture" else generate_token()
    response = unauthenticated_api_client.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data["name"] == animal.name


@pytest.mark.django_db
def test_oauth2_token_expiry(oauth2_admin_access_token):
    """
    Verify default expiration is 1 year
    """
    token = oauth2_admin_access_token[0]
    assert token.expires < datetime.now(tz=timezone.utc) + timedelta(weeks=53)


@pytest.mark.parametrize(
    "token, expected",
    [
        ("fixture", 201),
        ("bad", 401),
    ],
)
def test_oauth2_bearer_post(unauthenticated_api_client, oauth2_admin_access_token, admin_user, token, expected):
    """
    POST an animal with a bearer token.
    """
    url = get_relative_url("animal-list")
    token = oauth2_admin_access_token[1] if token == "fixture" else generate_token()
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.post(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data["name"] == "Fido"


@pytest.mark.parametrize(
    "token, expected",
    [
        ("fixture", 200),
        ("bad", 401),
    ],
)
def test_oauth2_bearer_patch(
    unauthenticated_api_client,
    oauth2_admin_access_token,
    animal,
    admin_user,
    token,
    expected,
):
    """
    PATCH an animal with a bearer token.
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1] if token == "fixture" else generate_token()
    data = {
        "name": "Fido",
    }
    response = unauthenticated_api_client.patch(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data["name"] == "Fido"


@pytest.mark.parametrize(
    "token, expected",
    [
        ("fixture", 200),
        ("bad", 401),
    ],
)
def test_oauth2_bearer_put(
    unauthenticated_api_client,
    oauth2_admin_access_token,
    animal,
    admin_user,
    token,
    expected,
):
    """
    PUT an animal with a bearer token.
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1] if token == "fixture" else generate_token()
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.put(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data["name"] == "Fido"


def test_oauth2_bearer_no_activitystream(unauthenticated_api_client, oauth2_admin_access_token, animal):
    """
    Ensure no activitystream entries for bearer token based auth
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1]
    existing_as_count = len(oauth2_admin_access_token[0].activity_stream_entries)

    response = unauthenticated_api_client.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.data["name"] == animal.name

    updated_token = OAuth2AccessToken.objects.get(token=oauth2_admin_access_token[0].token)
    assert len(updated_token.activity_stream_entries) == existing_as_count


@pytest.mark.parametrize(
    "scope, status",
    [
        ("write", 201),
        ("read write", 201),
        ("write read", 201),
        ("read", 403),
        ("openid", 403),
        ("roles", 403),
        ("openid roles", 403),
        ("read openid roles", 403),
        ("write openid roles", 201),
    ],
)
@pytest.mark.django_db
def test_oauth2_scope_permission(
    request,
    admin_user,
    oauth2_admin_access_token,
    unauthenticated_api_client,
    scope,
    status,
    only_oauth_scope_permission,
):
    """
    Ensure that scopes are adhered to for PATs
    """
    oauth2_admin_access_token[0].scope = scope
    oauth2_admin_access_token[0].save()

    url = get_relative_url("animal-list")
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.post(
        url,
        data=data,
        headers={"Authorization": f"Bearer {oauth2_admin_access_token[1]}"},
    )
    assert response.status_code == status, response.status_code


def test_oauth2_scope_permission_not_oauth(user, user_api_client, only_oauth_scope_permission):
    """
    Ensure that non-OAuth (but still authenticated) requests pass through.
    """

    url = get_relative_url("animal-list")
    data = {
        "name": "Fido",
        "owner": user.pk,
    }
    response = user_api_client.post(url, data=data)
    assert response.status_code == 201, response.status_code


def test_oauth2_scope_permission_not_authenticated(user, unauthenticated_api_client, only_oauth_scope_permission):
    """
    Ensure that non-authenticated are blocked.
    """

    url = get_relative_url("animal-list")
    data = {
        "name": "Fido",
        "owner": user.pk,
    }
    response = unauthenticated_api_client.post(url, data=data)
    assert response.status_code == 401, response.status_code


def test_oauth2_unsupported_media_type(user, user_api_client, only_oauth_scope_permission):
    url = get_relative_url("animal-upload")
    data = b"TESTDATA"
    response = user_api_client.post(url, data=data, content_type="application/octet-stream")
    assert response.status_code == 200, response.status_code


def test_oauth2_authentication_creates_activitystream_entry(
    unauthenticated_api_client,
    oauth2_admin_access_token,
    animal,
    django_capture_on_commit_callbacks,
):
    """
    Ensure that authenticating with OAuth2 and making a GET request does NOT
    create spurious activity stream entries (regression test).

    This tests that using OAuth2 authentication to simply read data doesn't
    incorrectly trigger activity stream entry creation.
    """
    # Get the count of all activity stream entries before the request
    initial_entry_count = Entry.objects.count()

    # Make an authenticated GET request using OAuth2 bearer token
    with django_capture_on_commit_callbacks(execute=True):
        url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
        access_token_obj = oauth2_admin_access_token[0]
        raw_token = oauth2_admin_access_token[1]
        response = unauthenticated_api_client.get(
            url,
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert response.status_code == 200
        assert response.data["name"] == animal.name

    # Verify OAuth2 was actually used by checking the token's last_used field was updated
    access_token_obj.refresh_from_db()
    assert access_token_obj.last_used is not None

    # Get the count of all activity stream entries after the request
    final_entry_count = Entry.objects.count()

    # No new activity stream entries should have been created by the GET request
    # (only the animal creation entry should exist, which was created before this test)
    assert final_entry_count == initial_entry_count


@pytest.mark.django_db
def test_oauth2_scope_not_mutated_after_permission_check(
    unauthenticated_api_client,
    oauth2_admin_access_token,
    animal,
    only_oauth_scope_permission,
):
    """
    Regression test for AAP-55298: Ensure that OAuth2ScopePermission.has_permission()
    does not permanently mutate the token's scope attribute.

    Previously, a write-scoped token would have ' read' appended to its scope
    during permission checking via ``request.auth.scope += ' read'``. This left
    the in-memory model instance with scope='write read', which could be
    persisted by any subsequent save() call, generating spurious activity stream
    entries.
    """
    access_token_obj = oauth2_admin_access_token[0]
    raw_token = oauth2_admin_access_token[1]

    # Ensure the token starts with scope="write" (the model default)
    access_token_obj.scope = "write"
    access_token_obj.save(update_fields=["scope"])

    # Make a GET request (read operation) using a write-scoped token.
    # OAuth2ScopePermission should temporarily expand the scope for the
    # permission check but restore it afterward.
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    response = unauthenticated_api_client.get(
        url,
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert response.status_code == 200

    # The in-memory token scope must still be "write" -- not "write read"
    access_token_obj.refresh_from_db()
    assert access_token_obj.scope == "write", f"Token scope was mutated to '{access_token_obj.scope}'; expected 'write'"

    # Also make a POST request (write operation) and verify scope is unchanged
    url = get_relative_url("animal-list")
    data = {"name": "ScopeTestAnimal", "owner": access_token_obj.user.pk}
    response = unauthenticated_api_client.post(
        url,
        data=data,
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert response.status_code == 201

    access_token_obj.refresh_from_db()
    assert access_token_obj.scope == "write", f"Token scope was mutated to '{access_token_obj.scope}' after POST; expected 'write'"


@pytest.mark.django_db
def test_oauth2_scope_no_activitystream_for_scope_field(
    unauthenticated_api_client,
    oauth2_admin_access_token,
    animal,
    only_oauth_scope_permission,
    django_capture_on_commit_callbacks,
):
    """
    Regression test for AAP-55298: Ensure that authenticated requests with a
    write-scoped OAuth2 token do not create activity stream entries recording
    a scope change from 'write' to 'write read'.
    """
    access_token_obj = oauth2_admin_access_token[0]
    raw_token = oauth2_admin_access_token[1]

    # Set token scope to 'write'
    access_token_obj.scope = "write"
    access_token_obj.save(update_fields=["scope"])

    # Record baseline activity stream count
    initial_entry_count = Entry.objects.count()

    # Make an authenticated request and flush on_commit callbacks
    with django_capture_on_commit_callbacks(execute=True):
        url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
        response = unauthenticated_api_client.get(
            url,
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert response.status_code == 200

    # No new activity stream entries should have been created
    final_entry_count = Entry.objects.count()
    assert final_entry_count == initial_entry_count, f"Expected no new activity stream entries, but {final_entry_count - initial_entry_count} were created"
