from ansible_base.lib.utils.response import get_relative_url


def test_validate_local_user(unauthenticated_api_client, admin_user, local_authenticator, settings_override_mutable, settings):
    url = get_relative_url('validate-local-account')
    data = {
        "username": admin_user.username,
        "password": "password",
    }
    response = unauthenticated_api_client.post(url, data=data)
    assert response.status_code == 200
    assert 'ansible_id' in response.data
    assert response.data['auth_code'] is not None

    # If we're missing RESOURCE_SERVER, we can't generate an auth code, so return null instead.
    with settings_override_mutable('RESOURCE_SERVER'):
        delattr(settings, 'RESOURCE_SERVER')

        response = unauthenticated_api_client.post(url, data=data)
        assert response.status_code == 200
        assert 'ansible_id' in response.data
        assert response.data['auth_code'] is None
