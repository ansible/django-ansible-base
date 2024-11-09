from django.apps import apps

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.migrations._utils import hash_tokens


def test_oauth2_migrations_hash_tokens(unauthenticated_api_client, oauth2_admin_access_token):
    """
    Force an unhashed token, run the migration function, and ensure the token is hashed.
    """
    unhashed_token = oauth2_admin_access_token[1]
    oauth2_admin_access_token[0].token = unhashed_token
    oauth2_admin_access_token[0].save()

    url = get_relative_url("user-me")
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {oauth2_admin_access_token[1]}'},
    )
    # When we set the token back to unhashed, we shouldn't be able to auth with it.
    assert response.status_code == 401

    hash_tokens(apps, None)

    url = get_relative_url("user-me")
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {oauth2_admin_access_token[1]}'},
    )
    # Now it's been hashed, so we can auth
    assert response.status_code == 200
    assert response.data['username'] == oauth2_admin_access_token[0].user.username

    # And if we re-run the hash function again for some reason, we never double-hash
    hash_tokens(apps, None)

    url = get_relative_url("user-me")
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {oauth2_admin_access_token[1]}'},
    )
    # We can still auth
    assert response.status_code == 200
    assert response.data['username'] == oauth2_admin_access_token[0].user.username
