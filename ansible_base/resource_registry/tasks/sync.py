from __future__ import annotations  # support python<3.10

import asyncio
import csv
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from io import StringIO, TextIOBase

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.db.utils import DatabaseError, IntegrityError
from django.utils import timezone
from requests import HTTPError

from ansible_base.resource_registry.models import Resource, ResourceType
from ansible_base.resource_registry.registry import get_registry
from ansible_base.resource_registry.rest_client import ResourceAPIClient, get_resource_server_client


class ManifestNotFound(HTTPError):
    """Raise when server returns 404 for a manifest"""


class ResourceDeletionError(DatabaseError):
    """Raise for deletion errors on Django ORM"""


class ResourceSyncHTTPError(HTTPError):
    """Custom catchall error"""


class SyncStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    NOOP = "noop"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


@dataclass
class ManifestItem:
    ansible_id: str
    resource_hash: str
    service_id: str | None = None
    resource_data: dict | None = None

    def __hash__(self):
        return hash(self.ansible_id)


@dataclass
class SyncResult:
    status: SyncStatus
    item: ManifestItem

    def __iter__(self):
        """Allows unpacking  status, item = SyncResult(...)"""
        return iter((self.status, self.item))


def create_api_client() -> ResourceAPIClient:
    """Factory for pre-configured ResourceAPIClient."""
    params = {"raise_if_bad_request": False}

    if jwt_user_id := getattr(settings, "RESOURCE_JWT_USER_ID", None):
        params["jwt_user_id"] = jwt_user_id

    service_path = getattr(settings, "RESOURCE_SERVICE_PATH", None)
    if not service_path:
        raise ValueError("RESOURCE_SERVICE_PATH is not set.")
    params["service_path"] = service_path

    client = get_resource_server_client(**params)
    return client


def fetch_manifest(
    resource_type_name: str,
    api_client: ResourceAPIClient | None = None,
) -> list[ManifestItem]:
    """Fetch RESOURCE_SERVER manifest, parses the CSV and returns a list."""
    api_client = api_client or create_api_client()
    api_client.raise_if_bad_request = False  # Status check is needed

    resp_metadata = api_client.get_service_metadata()
    resp_metadata.raise_for_status()
    service_id = resp_metadata.json()["service_id"]

    manifest_stream = api_client.get_resource_type_manifest(resource_type_name)
    if manifest_stream.status_code == 404:
        msg = f"manifest for {resource_type_name} NOT FOUND."
        raise ManifestNotFound(msg)

    try:
        manifest_stream.raise_for_status()
    except HTTPError as exc:
        raise ResourceSyncHTTPError() from exc

    csv_reader = csv.DictReader(StringIO(manifest_stream.text))
    return [ManifestItem(service_id=service_id, **row) for row in csv_reader]


def get_orphan_resources(
    resource_type_name: str,
    manifest_list: list[ManifestItem],
) -> QuerySet:
    """QuerySet with orphaned managed resources to be deleted."""
    return Resource.objects.filter(
        service_id=manifest_list[0].service_id,
        content_type__resource_type__name=resource_type_name,
    ).exclude(ansible_id__in=[item.ansible_id for item in manifest_list])


def delete_resource(resource: Resource):
    """Wrapper to delete content_object and its related Resource.
    It is up to the caller to wrap it on a database transaction.
    """
    try:
        resource.content_object.delete()
        return resource.delete()
    except DatabaseError as exc:  # pragma: no cover
        raise ResourceDeletionError() from exc


def get_managed_resource(manifest_item: ManifestItem) -> Resource | None:
    """Return an instance containing the local managed resource to process."""
    return Resource.objects.filter(
        ansible_id=manifest_item.ansible_id,
        service_id=manifest_item.service_id,
    ).first()


def get_resource_type_names() -> list[str]:
    """Ordered list of registered resource types."""
    registry = get_registry()
    resources = registry.get_resources()
    return [f"shared.{rt.model._meta.model_name}" for _, rt in sorted(resources.items())]


def _attempt_update_resource(
    manifest_item: ManifestItem,
    resource: Resource,
    resource_data: dict,
    **kwargs,
) -> SyncResult:
    """Try to update existing resource."""
    try:
        resource.update_resource(resource_data, partial=True, **kwargs)
    except IntegrityError:  # pragma: no cover
        return SyncResult(SyncStatus.CONFLICT, manifest_item)
    else:
        return SyncResult(SyncStatus.UPDATED, manifest_item)


def resource_sync(
    manifest_item: ManifestItem,
    api_client: ResourceAPIClient | None = None,
) -> SyncResult:
    """Uni-directional sync local resources from RESOURCE_SERVER resources."""
    api_client = api_client or create_api_client()
    local_managed_resource = get_managed_resource(manifest_item)
    resource_data = None
    resource_type_name = None
    unavailable = False  # for retry mechanism

    def set_resource_local_variables():
        """Inner caching function to avoid making unnecessary requests."""
        nonlocal resource_data
        nonlocal resource_type_name
        nonlocal unavailable
        if resource_data is None or resource_type_name is None:
            resp = api_client.get_resource(manifest_item.ansible_id)
            if 400 <= resp.status_code < 500:  # pragma: no cover
                unavailable = True
                return
            resp.raise_for_status()
            resource_data = resp.json()["resource_data"]
            resource_type_name = resp.json()["resource_type"]

    if local_managed_resource:
        # Exists locally: Compare and Update
        sc = local_managed_resource.content_type.resource_type.serializer_class
        local_hash = sc(local_managed_resource.content_object).get_hash()
        if manifest_item.resource_hash == local_hash:
            return SyncResult(SyncStatus.NOOP, manifest_item)
        set_resource_local_variables()
        if unavailable:  # pragma: no cover
            return SyncResult(SyncStatus.UNAVAILABLE, manifest_item)
        # bind fetched resource_data for allowing reporting.
        manifest_item.resource_data = resource_data
        return _attempt_update_resource(
            manifest_item,
            local_managed_resource,
            resource_data,
        )
    else:
        # New: Create it locally
        try:
            set_resource_local_variables()
            if unavailable:  # pragma: no cover
                return SyncResult(SyncStatus.UNAVAILABLE, manifest_item)
            manifest_item.resource_data = resource_data
            resource_type = ResourceType.objects.get(name=resource_type_name)
            Resource.create_resource(
                resource_type=resource_type,
                resource_data=resource_data,
                ansible_id=manifest_item.ansible_id,
                service_id=manifest_item.service_id,
            )
        except IntegrityError:
            return SyncResult(SyncStatus.CONFLICT, manifest_item)
        else:
            return SyncResult(SyncStatus.CREATED, manifest_item)


# https://docs.djangoproject.com/en/4.2/topics/async/#asgiref.sync.sync_to_async
async_resource_sync = sync_to_async(resource_sync)


@dataclass
class SyncExecutor:
    """Public Executor Implementing Sync and Async process."""

    api_client: ResourceAPIClient = field(default_factory=create_api_client)
    resource_type_names: list[str] | None = None
    retries: int = 0
    retrysleep: int = 30
    retain_seconds: int = 120
    stdout: TextIOBase | None = None
    unavailable: set = field(default_factory=set)
    attempts: int = 0
    deleted_count: int = 0
    asyncio: bool = False
    results: dict = field(default_factory=lambda: defaultdict(list))

    def write(self, text: str = ""):
        """Write to assigned IO or simply ignores the text."""
        if self.stdout:
            self.stdout.write(text)

    def _report_manifest_item(self, result: SyncResult):
        """Record status for each single resource of the manifest."""
        msg = f"{result.status.value.upper()} {result.item.ansible_id}"
        if result.item.resource_data:
            details = result.item.resource_data.get(
                "name",
                result.item.resource_data.get("username", ""),
            )
            msg += f" {details}"
        self.write(msg)

    def _report_results(self, results: list[SyncResult]):
        """Grouped results report at the end of the execution."""
        created_count = updated_count = conflicted_count = skipped_count = 0
        for status, manifest_item in results:
            self.results[status.value].append(manifest_item)
            self.unavailable.discard(manifest_item)
            # when python>3.10 replace with match
            if status == SyncStatus.UNAVAILABLE:  # pragma: no cover
                self.unavailable.add(manifest_item)
            elif status == SyncStatus.CREATED:
                created_count += 1
            elif status == SyncStatus.UPDATED:
                updated_count += 1
            elif status == SyncStatus.CONFLICT:
                conflicted_count += 1
            elif status == SyncStatus.NOOP:
                skipped_count += 1
            else:  # pragma: no cover
                raise TypeError("Unhandled SyncResult")

        self.write(
            f"Processed {len(results) + self.deleted_count} | "
            f"Created {created_count} | "
            f"Updated {updated_count} | "
            f"Conflict {conflicted_count} | "
            f"Unavailable {len(self.unavailable)} | "
            f"Skipped {skipped_count} | "
            f"Deleted {self.deleted_count}"
        )

    async def _a_process_manifest_item(self, manifest_item):  # pragma: no cover
        """Awaitable to process a manifest item using asyncio"""
        result = await async_resource_sync(manifest_item, self.api_client)
        self._report_manifest_item(result)
        return result

    async def _a_process_manifest_list(self, manifest_list):  # pragma: no cover
        """Awaitable to process a sequence of items using Asyncio."""
        queue = [self._a_process_manifest_item(item) for item in manifest_list]
        results = await asyncio.gather(*queue)
        self._report_results(results)

    def _process_manifest_item(self, manifest_item):
        """Process a manifest item"""
        result = resource_sync(manifest_item, self.api_client)
        self._report_manifest_item(result)
        return result

    def _process_manifest_list(self, manifest_list):
        """Process items sequentially."""
        results = [self._process_manifest_item(item) for item in manifest_list]
        self._report_results(results)

    def _cleanup_orphans(self, resource_type, manifest_list):
        """Delete local managed resources that are not part of the manifest."""
        resources_to_cleanup = get_orphan_resources(
            resource_type,
            manifest_list,
        )
        self.deleted_count = resources_to_cleanup.count()
        if self.deleted_count:
            self.write(f"Deleting {self.deleted_count} orphaned resources")
            for orphan in resources_to_cleanup:
                # If it was created in the latest X seconds, ignore it.
                if orphan.content_object.created >= timezone.now() - timedelta(seconds=self.retain_seconds):
                    continue
                try:
                    _sc = orphan.content_type.resource_type.serializer_class
                    data = _sc(orphan.content_object).data
                    data.update(orphan.summary_fields())
                    with transaction.atomic():
                        delete_resource(orphan)
                except ResourceDeletionError as exc:
                    self.write(f"Error deleting orphaned resources {str(exc)}")
                else:  # persist in the report
                    self.results["deleted"].append(data)

    def _handle_retries(self):  # pragma: no cover
        """Check if there are unavailable resources to re-try."""
        while self.unavailable and self.attempts < self.retries:
            self.write()
            self.write(f"Retry attempt {self.attempts}/{self.retries}")
            if self.retrysleep:
                self.write(f"waiting {self.retrysleep} seconds")
                time.sleep(self.retrysleep)
            if self.asyncio is True:
                asyncio.run(self._a_process_manifest_list(self.unavailable))
            else:
                self._process_manifest_list(self.unavailable)
            self.attempts += 1

    def _dispatch_sync_process(self, manifest_list: list[ManifestItem]):
        """Sync all the items from the manifest using either asyncio or sequentialy."""
        if self.asyncio is True:  # pragma: no cover
            self.write(f"Processing {len(manifest_list)} resources with asyncio executor.")
            self.write()
            asyncio.run(self._a_process_manifest_list(manifest_list))
        else:
            self.write(f"Processing {len(manifest_list)} resources sequentially.")
            self.write()
            self._process_manifest_list(manifest_list)

    def run(self):
        """Run the sync workflow.

        1. Iterate enabled resource types.
        2. Fetch RESOURCE_SERVER manifest.
        3. Cleanup orphaned resources (deleted remotely).
        4. Process the sync for each item in the manifest.
        5. Handle retries.
        """
        self.write("----- RESOURCE SYNC STARTED -----")
        self.write()

        for resource_type_name in get_resource_type_names():
            if self.resource_type_names and resource_type_name not in self.resource_type_names:
                # Skip types that are filtered out
                continue

            self.write(f">>> {resource_type_name}")
            try:
                manifest_list = fetch_manifest(resource_type_name, api_client=self.api_client)
            except ManifestNotFound as ex:
                self.write(str(ex))
                continue

            self._cleanup_orphans(resource_type_name, manifest_list)
            self._dispatch_sync_process(manifest_list)
            self._handle_retries()

            self.write()

        self.write("----- RESOURCE SYNC FINISHED -----")
