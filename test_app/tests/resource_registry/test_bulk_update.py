import uuid
from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import Resource


@pytest.fixture
def bulk_update_url():
    return get_relative_url("resource-list") + "bulk-update/"


@pytest.fixture
def three_users(django_user_model):
    users = []
    for i in range(3):
        users.append(django_user_model.objects.create_user(username=f"bulkuser{i}", password="password"))
    return users


@pytest.fixture
def user_resources(three_users):
    c_type = ContentType.objects.get_for_model(three_users[0])
    return [Resource.objects.get(object_id=u.pk, content_type=c_type.pk) for u in three_users]


class TestBulkUpdate:
    def test_bulk_update_service_id(self, admin_api_client, bulk_update_url, user_resources):
        """Bulk-update service_id for multiple resources in a single request."""
        new_service_id = str(uuid.uuid4())
        items = [{"ansible_id": str(r.ansible_id), "new_service_id": new_service_id} for r in user_resources]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 3
        assert resp.data["errors"] == []

        for r in user_resources:
            r.refresh_from_db()
            assert str(r.service_id) == new_service_id

    def test_bulk_update_ansible_id(self, admin_api_client, bulk_update_url, user_resources):
        """Bulk-update ansible_id (rename) for resources."""
        new_ids = [str(uuid.uuid4()) for _ in user_resources]
        items = [{"ansible_id": str(r.ansible_id), "new_ansible_id": new_id} for r, new_id in zip(user_resources, new_ids)]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 3

        for r, expected_id in zip(user_resources, new_ids):
            r.refresh_from_db()
            assert str(r.ansible_id) == expected_id

    def test_bulk_update_is_partially_migrated(self, admin_api_client, bulk_update_url, user_resources):
        """Bulk-update is_partially_migrated flag."""
        items = [{"ansible_id": str(r.ansible_id), "is_partially_migrated": True} for r in user_resources]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 3

        for r in user_resources:
            r.refresh_from_db()
            assert r.is_partially_migrated is True

    def test_bulk_update_mixed_fields(self, admin_api_client, bulk_update_url, user_resources):
        """Different items update different fields in the same batch."""
        new_service_id = str(uuid.uuid4())
        items = [
            {"ansible_id": str(user_resources[0].ansible_id), "new_service_id": new_service_id},
            {"ansible_id": str(user_resources[1].ansible_id), "is_partially_migrated": True},
            {"ansible_id": str(user_resources[2].ansible_id), "new_service_id": new_service_id, "is_partially_migrated": True},
        ]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 3

        user_resources[0].refresh_from_db()
        assert str(user_resources[0].service_id) == new_service_id

        user_resources[1].refresh_from_db()
        assert user_resources[1].is_partially_migrated is True

        user_resources[2].refresh_from_db()
        assert str(user_resources[2].service_id) == new_service_id
        assert user_resources[2].is_partially_migrated is True

    def test_bulk_update_not_found(self, admin_api_client, bulk_update_url, user_resources):
        """Items with non-existent ansible_id report errors but don't block the batch."""
        fake_id = str(uuid.uuid4())
        new_service_id = str(uuid.uuid4())
        items = [
            {"ansible_id": str(user_resources[0].ansible_id), "new_service_id": new_service_id},
            {"ansible_id": fake_id, "new_service_id": new_service_id},
        ]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 1
        assert len(resp.data["errors"]) == 1
        assert resp.data["errors"][0]["ansible_id"] == fake_id

        user_resources[0].refresh_from_db()
        assert str(user_resources[0].service_id) == new_service_id

    def test_bulk_update_empty_list(self, admin_api_client, bulk_update_url):
        """Empty list is valid and returns zero updates."""
        resp = admin_api_client.post(bulk_update_url, {"items": []}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 0
        assert resp.data["errors"] == []

    def test_bulk_update_missing_items_key(self, admin_api_client, bulk_update_url):
        """Payload without 'items' key returns 400."""
        resp = admin_api_client.post(bulk_update_url, {"ansible_id": str(uuid.uuid4())}, format="json")
        assert resp.status_code == 400
        assert "items" in resp.data["detail"].lower()

    def test_bulk_update_items_not_list(self, admin_api_client, bulk_update_url):
        """Payload where 'items' is not a list returns 400."""
        resp = admin_api_client.post(bulk_update_url, {"items": "not a list"}, format="json")
        assert resp.status_code == 400
        assert "list" in resp.data["detail"].lower()

    def test_bulk_update_exceeds_limit(self, admin_api_client, bulk_update_url):
        """Payload exceeding MAX_BULK_SIZE returns 400."""
        items = [{"ansible_id": str(uuid.uuid4()), "new_service_id": str(uuid.uuid4())} for _ in range(1001)]
        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 400
        assert "1000" in resp.data["detail"]

    def test_bulk_update_invalid_item(self, admin_api_client, bulk_update_url):
        """Invalid items (missing ansible_id) return serializer validation error."""
        items = [{"new_service_id": str(uuid.uuid4())}]
        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 400

    def test_bulk_update_no_update_fields(self, admin_api_client, bulk_update_url, user_resources):
        """Items with only ansible_id and no update fields are rejected."""
        items = [{"ansible_id": str(user_resources[0].ansible_id)}]
        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 400

    def test_bulk_update_permission_denied(self, user_api_client, bulk_update_url, user_resources):
        """Non-admin users cannot call bulk-update."""
        items = [{"ansible_id": str(user_resources[0].ansible_id), "new_service_id": str(uuid.uuid4())}]
        resp = user_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 403

    def test_bulk_update_resource_data(self, admin_api_client, bulk_update_url, three_users, user_resources):
        """Bulk-update resource_data updates the content object."""
        items = [
            {
                "ansible_id": str(user_resources[0].ansible_id),
                "resource_data": {"username": "renamed_user"},
            }
        ]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 1

        three_users[0].refresh_from_db()
        assert three_users[0].username == "renamed_user"

    def test_bulk_update_ansible_id_collision(self, admin_api_client, bulk_update_url, user_resources):
        """new_ansible_id collision reports per-item error without blocking other items."""
        existing_id = str(user_resources[1].ansible_id)
        original_failed_aid = str(user_resources[2].ansible_id)
        new_service_id = str(uuid.uuid4())
        items = [
            {"ansible_id": str(user_resources[0].ansible_id), "new_service_id": new_service_id},
            {"ansible_id": original_failed_aid, "new_ansible_id": existing_id},
        ]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 1
        assert len(resp.data["errors"]) == 1
        assert resp.data["errors"][0]["ansible_id"] == original_failed_aid
        # IntegrityError messages are sanitized — no schema details leaked
        assert "uniqueness or integrity constraint" in resp.data["errors"][0]["error"]

        # Verify successful item persisted in DB
        user_resources[0].refresh_from_db()
        assert str(user_resources[0].service_id) == new_service_id

        # Verify failed item was NOT changed (ansible_id remains its original value)
        user_resources[2].refresh_from_db()
        assert str(user_resources[2].ansible_id) == original_failed_aid

    def test_bulk_update_resource_data_not_manageable(self, admin_api_client, bulk_update_url, three_users, user_resources):
        """resource_data on a non-manageable resource type reports a per-item error."""
        from unittest.mock import PropertyMock, patch

        from ansible_base.resource_registry.models import ResourceType

        original_username = three_users[0].username
        new_service_id = str(uuid.uuid4())
        items = [
            {"ansible_id": str(user_resources[1].ansible_id), "new_service_id": new_service_id},
            {
                "ansible_id": str(user_resources[0].ansible_id),
                "resource_data": {"username": "should_not_apply"},
            },
        ]

        with patch.object(ResourceType, "can_be_managed", new_callable=PropertyMock, return_value=False):
            resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")

        assert resp.status_code == 200
        assert resp.data["updated"] == 1
        assert len(resp.data["errors"]) == 1
        assert "cannot be managed" in resp.data["errors"][0]["error"]

        # Verify successful item persisted in DB
        user_resources[1].refresh_from_db()
        assert str(user_resources[1].service_id) == new_service_id

        # Verify failed item's content object was NOT changed
        three_users[0].refresh_from_db()
        assert three_users[0].username == original_username

    def test_bulk_update_duplicate_ansible_id(self, admin_api_client, bulk_update_url, user_resources):
        """Duplicate ansible_id in the same batch is rejected."""
        aid = str(user_resources[0].ansible_id)
        items = [
            {"ansible_id": aid, "new_service_id": str(uuid.uuid4())},
            {"ansible_id": aid, "is_partially_migrated": True},
        ]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 400
        assert "Duplicate ansible_id" in resp.data["detail"]
        assert aid in resp.data["detail"]

    def test_bulk_update_unauthenticated(self, unauthenticated_api_client, bulk_update_url, user_resources):
        """Unauthenticated requests return 401."""
        items = [{"ansible_id": str(user_resources[0].ansible_id), "new_service_id": str(uuid.uuid4())}]
        resp = unauthenticated_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 401

    def test_bulk_update_resource_data_with_metadata(self, admin_api_client, bulk_update_url, three_users, user_resources):
        """resource_data combined with metadata fields updates both."""
        new_service_id = str(uuid.uuid4())
        items = [
            {
                "ansible_id": str(user_resources[0].ansible_id),
                "new_service_id": new_service_id,
                "is_partially_migrated": True,
                "resource_data": {"username": "combo_user"},
            }
        ]

        resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")
        assert resp.status_code == 200
        assert resp.data["updated"] == 1

        user_resources[0].refresh_from_db()
        assert str(user_resources[0].service_id) == new_service_id
        assert user_resources[0].is_partially_migrated is True

        three_users[0].refresh_from_db()
        assert three_users[0].username == "combo_user"

    def test_bulk_update_unexpected_exception(self, admin_api_client, bulk_update_url, user_resources):
        """Unexpected exceptions are caught and reported as per-item errors without crashing the batch."""
        from ansible_base.resource_registry.views import ResourceViewSet

        original_apply = ResourceViewSet._apply_resource_update
        second_item_service_id = str(uuid.uuid4())
        items = [
            {"ansible_id": str(user_resources[0].ansible_id), "new_service_id": str(uuid.uuid4())},
            {"ansible_id": str(user_resources[1].ansible_id), "new_service_id": second_item_service_id},
        ]

        call_count = {"n": 0}

        def raise_then_delegate(resource, item):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("unexpected")
            return original_apply(resource, item)

        with patch(
            "ansible_base.resource_registry.views.ResourceViewSet._apply_resource_update",
            side_effect=raise_then_delegate,
        ):
            resp = admin_api_client.post(bulk_update_url, {"items": items}, format="json")

        assert resp.status_code == 200
        assert resp.data["updated"] == 1
        assert len(resp.data["errors"]) == 1
        assert resp.data["errors"][0]["ansible_id"] == str(user_resources[0].ansible_id)
        assert "Internal error" in resp.data["errors"][0]["error"]

        # Verify second item was actually persisted
        user_resources[1].refresh_from_db()
        assert str(user_resources[1].service_id) == second_item_service_id
