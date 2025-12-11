from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from oauthlib.common import generate_token
from rest_framework.permissions import SAFE_METHODS

from ansible_base.activitystream.models import Entry
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2AccessToken


@pytest.fixture
def only_oauth_scope_permission(settings):
    from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

    with mock.patch('rest_framework.views.APIView.permission_classes', [OAuth2ScopePermission]):
        yield


def test_oauth2_bearer_get_user_correct(unauthenticated_api_client, oauth2_admin_access_token):
    """
    Perform a GET with a bearer token and ensure the authed user is correct.
    """
    url = get_relative_url("user-me")
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {oauth2_admin_access_token[1]}'},
    )
    assert response.status_code == 200
    assert response.data['username'] == oauth2_admin_access_token[0].user.username


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_get(unauthenticated_api_client, oauth2_admin_access_token, animal, token, expected):
    """
    GET an animal with a bearer token.
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1] if token == 'fixture' else generate_token()
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == animal.name


@pytest.mark.django_db
def test_oauth2_token_expiry(oauth2_admin_access_token):
    """
    Verify default expiration is 1 year
    """
    token = oauth2_admin_access_token[0]
    assert token.expires < datetime.now(tz=timezone.utc) + timedelta(weeks=53)


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 201),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_post(unauthenticated_api_client, oauth2_admin_access_token, admin_user, token, expected):
    """
    POST an animal with a bearer token.
    """
    url = get_relative_url("animal-list")
    token = oauth2_admin_access_token[1] if token == 'fixture' else generate_token()
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.post(
        url,
        data=data,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == 'Fido'


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_patch(unauthenticated_api_client, oauth2_admin_access_token, animal, admin_user, token, expected):
    """
    PATCH an animal with a bearer token.
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1] if token == 'fixture' else generate_token()
    data = {
        "name": "Fido",
    }
    response = unauthenticated_api_client.patch(
        url,
        data=data,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == 'Fido'


@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_oauth2_bearer_put(unauthenticated_api_client, oauth2_admin_access_token, animal, admin_user, token, expected):
    """
    PUT an animal with a bearer token.
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1] if token == 'fixture' else generate_token()
    data = {
        "name": "Fido",
        "owner": admin_user.pk,
    }
    response = unauthenticated_api_client.put(
        url,
        data=data,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['name'] == 'Fido'


def test_oauth2_bearer_no_activitystream(unauthenticated_api_client, oauth2_admin_access_token, animal):
    """
    Ensure no activitystream entries for bearer token based auth
    """
    url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
    token = oauth2_admin_access_token[1]
    existing_as_count = len(oauth2_admin_access_token[0].activity_stream_entries)

    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == 200
    assert response.data['name'] == animal.name

    updated_token = OAuth2AccessToken.objects.get(token=oauth2_admin_access_token[0].token)
    assert len(updated_token.activity_stream_entries) == existing_as_count


@pytest.mark.parametrize(
    'scope, status',
    [
        ('write', 201),
        ('read write', 201),
        ('write read', 201),
        ('read', 403),
    ],
)
@pytest.mark.django_db
def test_oauth2_scope_permission(request, admin_user, oauth2_admin_access_token, unauthenticated_api_client, scope, status, only_oauth_scope_permission):
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
        headers={'Authorization': f'Bearer {oauth2_admin_access_token[1]}'},
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
    data = b'TESTDATA'
    response = user_api_client.post(url, data=data, content_type='application/octet-stream')
    assert response.status_code == 200, response.status_code


def test_oauth2_authentication_creates_activitystream_entry(unauthenticated_api_client, oauth2_admin_access_token, animal, django_capture_on_commit_callbacks):
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
            headers={'Authorization': f'Bearer {raw_token}'},
        )
        assert response.status_code == 200
        assert response.data['name'] == animal.name

    # Verify OAuth2 was actually used by checking the token's last_used field was updated
    access_token_obj.refresh_from_db()
    assert access_token_obj.last_used is not None

    # Get the count of all activity stream entries after the request
    final_entry_count = Entry.objects.count()

    # No new activity stream entries should have been created by the GET request
    # (only the animal creation entry should exist, which was created before this test)
    assert final_entry_count == initial_entry_count


# =============================================================================
# OAuth2 Scope Validation Tests (Authentication Layer)
# =============================================================================
# These tests verify that scope checking happens at the authentication layer,
# returning 403 Forbidden when a token's scope doesn't permit the HTTP method.
# This matches the behavior of the permission-layer scope checking.
# =============================================================================


class TestOAuth2ScopeValidationInAuthentication:
    """
    Test suite for OAuth2 scope validation in the authentication layer.
    Tokens with 'read' scope should only be allowed for safe methods (GET, HEAD, OPTIONS).
    Tokens with 'write' scope should be allowed for all methods.
    """

    @pytest.mark.parametrize(
        'scope, method, should_succeed',
        [
            # read scope: safe methods should succeed
            ('read', 'get', True),
            ('read', 'head', True),
            ('read', 'options', True),
            # read scope: unsafe methods should fail
            ('read', 'post', False),
            ('read', 'put', False),
            ('read', 'patch', False),
            ('read', 'delete', False),
            # write scope: all methods should succeed
            ('write', 'get', True),
            ('write', 'head', True),
            ('write', 'options', True),
            ('write', 'post', True),
            ('write', 'put', True),
            ('write', 'patch', True),
            ('write', 'delete', True),
            # read write scope: all methods should succeed (test both orderings)
            ('read write', 'post', True),
            ('read write', 'put', True),
            ('read write', 'patch', True),
            ('read write', 'delete', True),
            ('write read', 'post', True),
            ('write read', 'put', True),
            ('write read', 'patch', True),
            ('write read', 'delete', True),
        ],
    )
    def test_scope_method_combinations(self, unauthenticated_api_client, oauth2_admin_access_token, animal, admin_user, scope, method, should_succeed):
        """
        Test all combinations of scope and HTTP method to verify correct authentication behavior.
        """
        oauth2_admin_access_token[0].scope = scope
        oauth2_admin_access_token[0].save()

        # Determine URL and data based on method
        if method == 'post':
            url = get_relative_url("animal-list")
            data = {"name": "Fido", "owner": admin_user.pk}
        elif method in ('get', 'head', 'options', 'delete'):
            url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
            data = None
        else:  # put, patch
            url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
            data = {"name": "Fido", "owner": admin_user.pk} if method == 'put' else {"name": "Fido"}

        # Make the request
        client_method = getattr(unauthenticated_api_client, method)
        kwargs = {'headers': {'Authorization': f'Bearer {oauth2_admin_access_token[1]}'}}
        if data is not None:
            kwargs['data'] = data

        response = client_method(url, **kwargs)

        if should_succeed:
            assert response.status_code != 403, f"Unexpected 403 for {method.upper()} with scope '{scope}'"
        else:
            assert response.status_code == 403, f"Expected 403 for {method.upper()} with scope '{scope}', got {response.status_code}"

    def test_read_scope_denial_error_message(self, unauthenticated_api_client, oauth2_admin_access_token, admin_user):
        """
        Verify the error message when a read-only token attempts an unsafe method.
        """
        oauth2_admin_access_token[0].scope = 'read'
        oauth2_admin_access_token[0].save()

        url = get_relative_url("animal-list")
        data = {"name": "Fido", "owner": admin_user.pk}
        response = unauthenticated_api_client.post(
            url,
            data=data,
            headers={'Authorization': f'Bearer {oauth2_admin_access_token[1]}'},
        )

        assert response.status_code == 403
        error_detail = response.data.get('detail', '')
        # Verify key parts of the error message
        assert 'read' in error_detail.lower()
        assert 'POST' in error_detail
        assert 'safe methods' in error_detail.lower()
        # Verify SAFE_METHODS are mentioned dynamically
        for method in SAFE_METHODS:
            assert method in error_detail

    @pytest.mark.parametrize(
        'scope, method, expected_log_keyword, expected_log_level',
        [
            ('read', 'post', 'attempted', 'WARNING'),  # Denied - should log WARNING with "attempted"
            ('write', 'get', 'performed', 'INFO'),  # Allowed - should log INFO with "performed"
            ('write', 'post', 'performed', 'INFO'),  # Allowed - should log INFO with "performed"
        ],
    )
    def test_scope_logging(
        self, unauthenticated_api_client, oauth2_admin_access_token, animal, admin_user, caplog, scope, method, expected_log_keyword, expected_log_level
    ):
        """
        Verify that authentication logging uses correct terminology and log levels:
        - 'attempted' at WARNING level for denied requests
        - 'performed' at INFO level for successful requests
        """
        import logging

        oauth2_admin_access_token[0].scope = scope
        oauth2_admin_access_token[0].save()

        if method == 'post':
            url = get_relative_url("animal-list")
            data = {"name": "Fido", "owner": admin_user.pk}
        else:
            url = get_relative_url("animal-detail", kwargs={"pk": animal.pk})
            data = None

        client_method = getattr(unauthenticated_api_client, method)
        kwargs = {'headers': {'Authorization': f'Bearer {oauth2_admin_access_token[1]}'}}
        if data is not None:
            kwargs['data'] = data

        with caplog.at_level(logging.DEBUG, logger='ansible_base.oauth2_provider.authentication'):
            response = client_method(url, **kwargs)

        # Find the relevant log record
        matching_records = [r for r in caplog.records if expected_log_keyword in r.message]
        assert matching_records, f"Expected log message containing '{expected_log_keyword}' not found in: {[r.message for r in caplog.records]}"

        # Verify log level
        assert matching_records[0].levelname == expected_log_level, f"Expected log level {expected_log_level}, got {matching_records[0].levelname}"

        # Additional assertion: denied requests should mention "does not permit"
        if expected_log_keyword == 'attempted':
            assert response.status_code == 403
            assert any(
                'does not permit' in r.message for r in caplog.records
            ), f"Expected denial reason in log not found in: {[r.message for r in caplog.records]}"
