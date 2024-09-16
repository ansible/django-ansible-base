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


def test_resource_type_manifest_default(admin_api_client, admin_user, user):
    r_text = get_users_manifest(admin_api_client)
    assert str(user.resource.ansible_id) in r_text
    assert str(admin_user.resource.ansible_id) in r_text


def test_resource_manifest_non_default_service_id(admin_api_client, admin_user, user):
    "Tests that we can use query param to filter the manifest list to a different service_id"
    # Expect a 404 because no records should be returned for this service_id
    r_text = get_users_manifest(admin_api_client, data={'service_id': str(uuid4())}, expect=404)
    assert str(user.resource.ansible_id) not in r_text

    user.resource.service_id = str(uuid4())
    user.resource.save(update_fields=['service_id'])

    # Expect to get some user entries, but this particular user will not be returned
    r_text = get_users_manifest(admin_api_client)
    assert str(user.resource.ansible_id) not in r_text

    # Filtering by the modified service_id should give exactly ONE entry
    r_text = get_users_manifest(admin_api_client, data={'service_id': str(user.resource.service_id)}, expect=200)
    assert len(r_text.strip().split('\n')) == 2  # headers and the ONE entry
    assert str(admin_user.resource.ansible_id) not in r_text
    assert str(user.resource.ansible_id) in r_text


def test_resource_manifest_no_service_id_filter(admin_api_client, admin_user, user):
    user.resource.service_id = str(uuid4())
    user.resource.save(update_fields=['service_id'])

    r_text = get_users_manifest(admin_api_client, data={'service_id': ''}, expect=200)
    assert str(user.resource.ansible_id) in r_text
    assert str(admin_user.resource.ansible_id) in r_text
