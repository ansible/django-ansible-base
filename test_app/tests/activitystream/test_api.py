import datetime

import pytest
from crum import impersonate
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils.http import urlencode

from ansible_base.activitystream.models import Entry


def test_activitystream_api_read(admin_api_client, user):
    """
    Test that we can read activity stream events via the API.
    """
    url = reverse("activitystream-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["count"] > 0
    assert response.data["results"][0]["operation"] == "create"
    # Ensure that even though we're storing a string here, the serializer is converting it back to the correct type.
    assert response.data["results"][0]["changes"]["added_fields"]["id"] == int(user.id)
    count = response.data["count"]
    original_name = user.first_name
    user.first_name = "Firstname"
    user.save()
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["count"] == count + 1
    assert response.data["results"][0]["operation"] == "update"
    assert response.data["results"][0]["changes"]["changed_fields"]["first_name"] == [original_name, user.first_name]


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


def test_activitystream_api_deleted_model(admin_api_client):
    """
    In Activity Stream we store GFKs to models. But over the lifetime of an
    application, models can be deleted or renamed or otherwise come to no longer
    exist. We shouldn't crash when we encounter these.
    """
    ct = ContentType.objects.create(app_label="test_app", model="NonExistentModel")
    entry = Entry.objects.create(
        operation="update",
        content_type=ct,
        object_id=1337,
        changes={
            "changed_fields": {
                "name": ("Fido", "Bob The Fish"),
                "is_cool_fish": ("False", "True"),
            },
            "added_fields": {},
            "removed_fields": {},
        },
    )
    url = reverse("activitystream-detail", args=[entry.id])
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["content_type"] == ct.id
    assert response.data["changes"]["changed_fields"]["name"] == ["Fido", "Bob The Fish"]
    assert response.data["changes"]["changed_fields"]["is_cool_fish"] == ["False", "True"]


def test_activitystream_api_deleted_related_model(admin_api_client, animal):
    """
    Similar to the above test, but for the related_* fields.
    """
    ct = ContentType.objects.create(app_label="test_app", model="NonExistentModel")
    entry = Entry.objects.create(
        operation="associate",
        content_object=animal,
        related_content_type=ct,
        related_object_id=1337,
        changes=None,
    )
    url = reverse("activitystream-detail", args=[entry.id])
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["related_content_type"] == ct.id
    assert response.data["related_object_id"] == "1337"


def test_activitystream_api_ordering(admin_api_client, animal, user, random_user):
    url = reverse("activitystream-list")
    query_params = {
        'order_by': '-id',
    }
    response = admin_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200
    assert response.data['count'] > 2
    assert response.data['results'][0]['id'] == Entry.objects.last().id


@pytest.mark.xfail(reason="TODO: Decide if we really want to exclude these from list view.")
def test_activitystream_api_related_fks_not_in_list_view(admin_api_client, animal, user, random_user):
    """
    Ensure that we don't link to related objects in the list view.
    """
    animal.owner = random_user
    animal.save()
    url = reverse("activitystream-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    entry = response.data["results"][0]
    assert entry["operation"] == "update"
    assert entry["changes"]["changed_fields"]["owner"] == [user.id, random_user.id]
    assert 'changes.owner' not in entry['related']


def test_activitystream_api_related_fks_in_detail_view(admin_api_client, animal, user, random_user):
    """
    Ensure that we link to related objects in the detail view.
    """
    animal.owner = random_user
    animal.save()
    url = reverse("activitystream-detail", args=[animal.activity_stream_entries.last().id])
    response = admin_api_client.get(url)
    assert response.status_code == 200
    entry = response.data
    assert entry["operation"] == "update"
    assert entry["changes"]["changed_fields"]["owner"] == [user.id, random_user.id]
    assert 'changes.owner' in entry['related']


def test_activitystream_api_related_fks_refused_for_bad_time_delta(admin_api_client, animal, user, random_user):
    """
    Ensure that we don't link to related objects that were created after the activity stream entry.
    """
    animal.owner = random_user
    animal.save()

    last_entry = animal.activity_stream_entries.last()
    random_user.created = last_entry.created + datetime.timedelta(days=1)
    random_user.save()

    url = reverse("activitystream-detail", args=[last_entry.id])
    response = admin_api_client.get(url)
    assert response.status_code == 200
    entry = response.data
    assert entry["operation"] == "update"
    assert entry["changes"]["changed_fields"]["owner"] == [user.id, random_user.id]
    assert 'changes.owner' not in entry['related']  # Don't link it, it's too new!


@pytest.mark.parametrize(
    "is_list_view",
    [
        pytest.param(True, id="list view"),
        pytest.param(False, id="detail view"),
    ],
)
def test_activitystream_api_related_content_object(admin_api_client, animal, is_list_view):
    """
    Ensure that we can link to the thing we're an entry for.
    """
    if is_list_view:
        url = reverse("activitystream-list")
    else:
        url = reverse("activitystream-detail", args=[animal.activity_stream_entries.last().id])

    response = admin_api_client.get(url)
    assert response.status_code == 200

    if is_list_view:
        entry = response.data["results"][0]
    else:
        entry = response.data

    assert entry["operation"] == "create"
    expected_url = reverse("animal-detail", args=[animal.id])
    assert entry["related"]["content_object"] == expected_url


@pytest.mark.parametrize(
    "is_list_view",
    [
        pytest.param(True, id="list view"),
        pytest.param(False, id="detail view"),
    ],
)
def test_activitystream_api_related_related_content_object(admin_api_client, animal, random_user, is_list_view):
    """
    Ensure that we can link to the associated object if we're describing an m2m association.

    Should show in both list and detail views.
    """
    animal.people_friends.add(random_user)

    if is_list_view:
        url = reverse("activitystream-list")
    else:
        url = reverse("activitystream-detail", args=[animal.activity_stream_entries.last().id])

    response = admin_api_client.get(url)
    assert response.status_code == 200

    if is_list_view:
        entry = response.data["results"][0]
    else:
        entry = response.data

    assert entry["operation"] == "associate"
    expected_url = reverse("user-detail", args=[random_user.id])
    assert entry["related"]["related_content_object"] == expected_url


@pytest.mark.parametrize(
    "is_list_view",
    [
        pytest.param(True, id="list view"),
        pytest.param(False, id="detail view"),
    ],
)
@pytest.mark.parametrize(
    "field_name,expected_key,expected_value",
    [
        ("created_by", "username", "user"),
        ("content_object", "name", "Fido"),
        ("changes.modified_by", "username", "user"),
        ("changes.owner", "username", "admin"),
    ],
)
def test_activitystream_api_summary_fields(admin_api_client, animal, admin_user, user, is_list_view, field_name, expected_key, expected_value):
    """
    Ensure that summary_fields show up and include changed fields.

    Should show in both list and detail views.
    """
    animal.owner = admin_user
    animal.name = "Fido"
    with impersonate(user):
        animal.save()

    if is_list_view:
        url = reverse("activitystream-list")
    else:
        url = reverse("activitystream-detail", args=[animal.activity_stream_entries.last().id])

    query_params = {
        'page_size': 100,
    }
    response = admin_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200

    if is_list_view:
        entry = response.data["results"][0]
    else:
        entry = response.data

    assert entry["operation"] == "update"
    assert field_name in entry["summary_fields"]
    assert entry["summary_fields"][field_name][expected_key] == expected_value
