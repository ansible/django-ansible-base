from uuid import uuid4

from ansible_base.lib.utils.response import get_relative_url


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

    # Expect this user to be returned since it is managed by the service
    r_text = get_users_manifest(admin_api_client)
    assert str(user.resource.ansible_id) in r_text

    # set the user as managed by another service
    new_sid = str(uuid4())
    user.resource.service_id = new_sid
    user.resource.save()

    # User should not be returned
    r_text = get_users_manifest(admin_api_client, data={'service_id': str(uuid4())})
    assert str(user.resource.ansible_id) not in r_text

    r_text = get_users_manifest(admin_api_client)
    assert str(user.resource.ansible_id) not in r_text

    # Now include the resources from our new "service"
    r_text = get_users_manifest(admin_api_client, data={'service_id': new_sid}, expect=200)
    assert str(user.resource.ansible_id) in r_text


def test_resource_manifest_no_service_id_filter(admin_api_client, admin_user, user):
    user.resource.service_id = str(uuid4())
    user.resource.save(update_fields=['service_id'])

    r_text = get_users_manifest(admin_api_client, data={'service_id': 'all'}, expect=200)
    assert str(user.resource.ansible_id) in r_text
    assert str(admin_user.resource.ansible_id) in r_text
