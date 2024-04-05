from unittest import mock

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse

from ansible_base.activitystream.views import _permission_classes


def test_activitystream_api_read(admin_api_client, user):
    """
    Test that we can read activity stream events via the API.
    """
    url = reverse("activitystream-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["count"] > 0
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
    "permission_classes,who",
    [
        (["rest_framework.permissions.IsAuthenticated"], "user"),
        (["ansible_base.lib.utils.views.permissions.IsSuperuser"], "admin"),
        (settings.ANSIBLE_BASE_ACTIVITYSTREAM_VIEW_PERMISSION_CLASSES, "admin"),
    ],
)
def test_activitystream_api_permission_classes(admin_api_client, user_api_client, permission_classes, who):
    """
    Test that access to the activity stream can be configured with
    settings.ANSIBLE_BASE_ACTIVITYSTREAM_VIEW_PERMISSION_CLASSES.

    :param permission_classes: List of permission classes to use.
    :param who: "admin" or "user" specifying who should have access. (admin always has access)
    """
    url = reverse("activitystream-list")

    # This is kind of an ugly way to test this, but we want to cover _permission_classes().
    # We _could_ override has_permission() and compute the permission every time, but that's slower (due to importing).
    with override_settings(ANSIBLE_BASE_ACTIVITYSTREAM_VIEW_PERMISSION_CLASSES=permission_classes):
        with mock.patch("ansible_base.activitystream.views.EntryReadOnlyViewSet.permission_classes", _permission_classes()):
            # Admin can always access
            response = admin_api_client.get(url)
            assert response.status_code == 200

            # User can access if the permission class allows it
            response = user_api_client.get(url)
            if who == "user":
                assert response.status_code == 200
            else:
                assert response.status_code == 403


def test_activitystream_api_permission_classes_invalid():
    """
    Test that providing invalid permission classes in settings provides a reasonable error.
    """
    with override_settings(ANSIBLE_BASE_ACTIVITYSTREAM_VIEW_PERMISSION_CLASSES=["foo.bar.Baz"]):
        with pytest.raises(ImproperlyConfigured) as excinfo:
            _permission_classes()
    assert "Could not find permission class 'foo.bar.Baz'" in str(excinfo.value)
