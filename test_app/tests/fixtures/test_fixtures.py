import pytest


@pytest.mark.django_db
def test_clients_do_not_conflict(unauthenticated_api_client, user_api_client, admin_api_client):
    assert dict(user_api_client.cookies) != dict(admin_api_client.cookies)
    assert dict(unauthenticated_api_client.cookies) == {}
