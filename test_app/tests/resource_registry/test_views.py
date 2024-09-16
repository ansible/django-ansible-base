from uuid import uuid4


from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import ResourceType


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


def get_users_manifest(client, data=None, expect=200):
    if data is None:
        data = {}
    url = get_relative_url('resourcetype-manifest', kwargs={'name': 'shared.user'})
    r = client.get(url, data=data)
    assert r.status_code == expect, f'request data: {data}, url: {url}, response: {r}'
    return '\n'.join([str(line) for line in r])


def test_resource_type_manifest(admin_api_client, user):
    r_text = get_users_manifest(admin_api_client)
    assert str(user.resource.ansible_id) in r_text

    # Expect a 404 because no records should be returned for this service_id
    r_text = get_users_manifest(admin_api_client, data={'service_id': str(uuid4())}, expect=404)
    assert str(user.resource.ansible_id) not in r_text

    user.resource.service_id = str(uuid4())
    user.resource.save(update_fields=['service_id'])

    # Expect to get some user entries, but this particular user will not be returned
    r_text = get_users_manifest(admin_api_client)
    assert str(user.resource.ansible_id) not in r_text
