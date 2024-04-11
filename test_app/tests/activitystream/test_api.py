import pytest
from django.urls import reverse
from django.utils.http import urlencode


def test_activitystream_api_read(admin_api_client, user):
    """
    Test that we can read activity stream events via the API.
    """
    url = reverse("activitystream-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["count"] > 0
    assert response.data["results"][-1]["operation"] == "create"
    # Ensure that even though we're storing a string here, the serializer is converting it back to the correct type.
    assert response.data["results"][-1]["changes"]["added_fields"]["id"] == int(user.id)
    count = response.data["count"]
    original_name = user.first_name
    user.first_name = "Firstname"
    user.save()
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["count"] == count + 1
    assert response.data["results"][-1]["operation"] == "update"
    assert response.data["results"][-1]["changes"]["changed_fields"]["first_name"] == [original_name, user.first_name]


def test_activitystream_api_read_only(admin_api_client, user):
    """
    Test that we can *only* read activity stream events via the API.
    """
    url = reverse("activitystream-list")
    response = admin_api_client.post(url)
    assert response.status_code == 405
    response = admin_api_client.put(url)
    assert response.status_code == 405
    response = admin_api_client.patch(url)
    assert response.status_code == 405
    response = admin_api_client.delete(url)
    assert response.status_code == 405


@pytest.mark.parametrize(
    "has_rbac_app,who",
    [
        (True, "user"),
        (False, "admin"),
    ],
)
def test_activitystream_api_permission_classes(admin_api_client, user_api_client, has_rbac_app, who, settings):
    """
    Test that access to the activity stream is dynamically determined based on
    whether or not RBAC is enabled.

    If RBAC is enabled, then it locks down permissions on its own, so we allow IsAuthenticated.
    If RBAC is not enabled, then we require IsSuperuser.
    """
    url = reverse("activitystream-list")

    if 'ansible_base.rbac' in settings.INSTALLED_APPS:
        if not has_rbac_app:
            settings.INSTALLED_APPS.remove('ansible_base.rbac')
    else:
        if has_rbac_app:
            settings.INSTALLED_APPS.append('ansible_base.rbac')

    # Admin can always access
    response = admin_api_client.get(url)
    assert response.status_code == 200

    # User can access if the permission class allows it
    response = user_api_client.get(url)
    if who == "user":
        assert response.status_code == 200
    else:
        assert response.status_code == 403


def test_activitystream_api_filtering(admin_api_client, user):
    url = reverse("activitystream-list")
    query_params = {
        'operation__exact': 'create',
        'content_type__model__exact': 'user',
        'changes__added_fields__id__exact': user.id,
    }
    response = admin_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200
    assert response.data['count'] == 1
    assert response.data['results'][0]['operation'] == 'create'
    assert response.data['results'][0]['changes']['added_fields']['id'] == user.id  # Ensure types get restored

    user.first_name = "Jane"
    user.last_name = "Doe"
    user.save()

    query_params = {'changes__changed_fields__last_name__1__iexact': 'dOe'}
    response = admin_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200
    assert response.data['count'] == 1
