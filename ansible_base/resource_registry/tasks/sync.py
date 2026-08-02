from __future__ import annotations  # support python<3.10

import asyncio
import csv
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from io import StringIO, TextIOBase

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.db.utils import Error, IntegrityError
from requests import HTTPError

from ansible_base.lib.utils.apps import is_rbac_installed
from ansible_base.rbac.role_sync_utils import (  # noqa: F401 — re-exported for backward compatibility
    AssignmentTuple,
    create_local_assignment,
    delete_local_assignment,
    get_ansible_id_or_pk,
    get_content_object,
    get_local_assignments,
)
from ansible_base.resource_registry.constants import SHARED_USER_RESOURCE_TYPE
from ansible_base.resource_registry.models import Resource, ResourceType
from ansible_base.resource_registry.models.service_identifier import service_id
from ansible_base.resource_registry.registry import get_registry
from ansible_base.resource_registry.rest_client import ResourceAPIClient, get_resource_server_client

logger = logging.getLogger('ansible_base.resources_api.tasks.sync')

# Must match defaults in lib/dynamic_config/settings_logic.py resource_registry_defaults
DEFAULT_SYNC_PAGE_SIZE = 50
DEFAULT_SYNC_JWT_EXPIRATION = 60


class ManifestNotFound(HTTPError):
    """Raise when server returns 404 for a manifest"""


class ResourceDeletionError(Error):
    """Raise for deletion errors on Django ORM"""


class ResourceSyncHTTPError(HTTPError):
    """Custom catchall error"""


class SkipResource(ValidationError):
    """To raise by serializers if the item should be skipped"""

    default_detail = "The specified content_type slug was not found."
    default_code = "content_type_does_not_exist"


class SyncStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    NOOP = "noop"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass
class ManifestItem:
    ansible_id: str
    resource_hash: str
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


@dataclass
class RemoteAssignmentResult:
    """Result of fetching remote assignments, including completeness status.

    When ``is_complete`` is False the caller must not use the partial
    ``assignments`` set for deletion decisions — doing so would remove
    local assignments that simply weren't fetched.
    """

    assignments: set[AssignmentTuple] = field(default_factory=set)
    is_complete: bool = False


class RemoteAssignmentFetcher:
    """Fetches role assignments from a remote resource server with pagination.

    Collects user and team assignments into a single set.  If any page
    request fails the fetcher stops early and marks the result as
    incomplete so the caller can skip deletions safely.
    """

    def __init__(self, api_client: ResourceAPIClient, page_size: int | None = None, service_filter: str | None = None):
        self.api_client = api_client
        self.assignments: set[AssignmentTuple] = set()
        self.page_size = page_size if page_size is not None else getattr(settings, 'RESOURCE_SYNC_PAGE_SIZE', DEFAULT_SYNC_PAGE_SIZE)
        self.service_filter = service_filter

    def fetch(self) -> RemoteAssignmentResult:
        """Paginate user then team assignments and return the result.

        If user pagination fails, team pagination is skipped entirely
        because the result will be incomplete regardless.
        """
        from ansible_base.rbac.models.role import RoleDefinition

        self.local_role_names: set[str] = set(RoleDefinition.objects.values_list('name', flat=True))

        users_ok = self._paginate(self.api_client.list_user_assignments, 'user_ansible_id', 'user')
        if not users_ok:
            return RemoteAssignmentResult(assignments=self.assignments, is_complete=False)

        teams_ok = self._paginate(self.api_client.list_team_assignments, 'team_ansible_id', 'team')
        return RemoteAssignmentResult(assignments=self.assignments, is_complete=teams_ok)

    def _paginate(self, list_fn, actor_id_key: str, assignment_type: str) -> bool:
        """Paginate a single assignment endpoint, adding results to ``self.assignments``.

        Returns True if all pages were fetched successfully, False on any error.
        """
        page = 1
        try:
            while True:
                filters = {'page': page, 'page_size': self.page_size}
                if self.service_filter:
                    filters['content_type__service'] = self.service_filter
                resp = list_fn(filters=filters)
                if resp.status_code != 200:
                    logger.warning(f"Failed to fetch {assignment_type} assignments page {page}: HTTP {resp.status_code}")
                    return False

                data = resp.json()
                for assignment in data.get('results') or []:
                    role_name = assignment['role_definition']
                    if role_name not in self.local_role_names:
                        logger.debug(f"Skipping remote {assignment_type} assignment with unknown local role: {role_name}")
                        continue
                    ansible_id_or_pk = assignment.get('object_ansible_id') or assignment.get('object_id')
                    self.assignments.add(
                        AssignmentTuple(
                            actor_ansible_id=assignment[actor_id_key],
                            ansible_id_or_pk=ansible_id_or_pk,
                            role_definition_name=role_name,
                            assignment_type=assignment_type,
                        )
                    )

                if not data.get('next'):
                    return True

                page += 1
                logger.debug(f"Fetching next page {page} of {assignment_type} assignments")
        except Exception:
            logger.exception(f"Failed to fetch remote {assignment_type} assignments")
            return False


def get_remote_assignments(api_client: ResourceAPIClient, page_size: int | None = None, service_filter: str | None = None) -> RemoteAssignmentResult:
    """Fetch remote assignments from the resource server and convert to tuples.

    Returns a ``RemoteAssignmentResult`` so the caller can distinguish a
    complete fetch from a partial one (e.g. due to HTTP errors or
    timeouts mid-pagination).
    """
    return RemoteAssignmentFetcher(api_client, page_size=page_size, service_filter=service_filter).fetch()


def create_api_client() -> ResourceAPIClient:
    """Factory for pre-configured ResourceAPIClient."""
    params = {"raise_if_bad_request": False}

    if jwt_user_id := getattr(settings, "RESOURCE_JWT_USER_ID", None):
        params["jwt_user_id"] = jwt_user_id

    service_path = getattr(settings, "RESOURCE_SERVICE_PATH", None)
    if not service_path:
        raise ValueError("RESOURCE_SERVICE_PATH is not set.")
    params["service_path"] = service_path
    params["jwt_expiration"] = getattr(settings, "RESOURCE_SYNC_JWT_EXPIRATION", DEFAULT_SYNC_JWT_EXPIRATION)

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

    manifest_stream = api_client.get_resource_type_manifest(resource_type_name, filters={"service_id": service_id()})
    if manifest_stream.status_code == 404:
        msg = f"manifest for {resource_type_name} NOT FOUND."
        raise ManifestNotFound(msg)

    try:
        manifest_stream.raise_for_status()
    except HTTPError as exc:
        raise ResourceSyncHTTPError() from exc

    csv_reader = csv.DictReader(StringIO(manifest_stream.text))
    return [ManifestItem(**row) for row in csv_reader]


def get_orphan_resources(
    resource_type_name: str,
    manifest_list: list[ManifestItem],
) -> QuerySet:
    """QuerySet with orphaned managed resources to be deleted."""
    queryset = (
        Resource.objects.filter(
            content_type__resource_type__name=resource_type_name,
        )
        .exclude(ansible_id__in=[item.ansible_id for item in manifest_list])
        .exclude(
            service_id=service_id(),
            is_partially_migrated=False,
        )
    )

    # Exclude system user from deletion, consistent with manifest endpoint
    if resource_type_name == SHARED_USER_RESOURCE_TYPE:
        from ansible_base.lib.utils.models import get_system_user

        system_user = get_system_user()
        if system_user:
            queryset = queryset.exclude(object_id=system_user.id)

    return queryset


def delete_resource(resource: Resource):
    """Wrapper to delete content_object and its related Resource.
    It is up to the caller to wrap it on a database transaction.
    """
    try:
        return resource.delete_resource()
    except Error as exc:  # pragma: no cover
        logger.exception(f"Failed to delete resource {resource.ansible_id}")
        raise ResourceDeletionError() from exc


def get_managed_resource(manifest_item: ManifestItem) -> Resource | None:
    """Return an instance containing the local managed resource to process."""
    return Resource.objects.filter(
        ansible_id=manifest_item.ansible_id,
    ).first()


def get_resource_type_names() -> list[str]:
    """Ordered list of registered resource types."""
    registry = get_registry()
    resources = registry.get_resources()
    return [f"shared.{rt.model._meta.model_name}" for _, rt in sorted(resources.items())]


def _handle_conflict(resource_data: dict, resource_type: ResourceType, api_client: ResourceAPIClient):
    # How might we end up with a conflict?
    # - get_orphan_resources ignores resources that are owned by the service and have
    #   is partially migrated set to false. We could be conflicting with one of those.
    # - You could rename A --> B and B --> C. If A is updated before B is, then we will
    #   end up needing to update B before we can update A.
    # - You could rename A --> B and B --> A. If this happens, there is really no recovery.
    #   Updating either would result in a conflict. We would have to set A or B to some
    #   temporary value. Hopefully this will never happen since this scenario would be
    #   incredibly difficult to pull off.

    conflict_resource = resource_type.get_conflicting_resource(resource_data)

    if conflict_resource is None:
        return

    resp = api_client.get_resource(conflict_resource.ansible_id)

    # If the conflicting resource doesn't exist on the server, just go ahead and delete it.
    # This will most likely happen with resources that are ignored by get_orphan_resources.
    if resp.status_code == 404:
        delete_resource(conflict_resource)

    # If the resource does exist, lets update it first. Hopefully this doesn't also result
    # in a duplicate key error. If it does, we're cooked.
    elif resp.status_code == 200:
        data = resp.json()
        conflict_resource.update_resource(
            resource_data=data["resource_data"], service_id=data["service_id"], is_partially_migrated=data["is_partially_migrated"]
        )
    else:
        raise ResourceSyncHTTPError(f"Received a bad error code from the resource server: {resp.status_code}")


def _attempt_update_resource(
    manifest_item: ManifestItem,
    resource: Resource,
    resource_data: dict,
    api_client: ResourceAPIClient,
    **kwargs,
) -> SyncResult:
    """Try to update existing resource."""
    try:
        if not resource.update_resource(resource_data, partial=True, **kwargs):
            return SyncResult(SyncStatus.NOOP, manifest_item)
    except IntegrityError:  # pragma: no cover
        # This typically means that there was a duplicate key error. To mitigate this
        # we will attempt to handle the conflicting resource and perform the operation
        # again.
        try:
            _handle_conflict(resource_data, resource.resource_type_obj, api_client)
            resource.update_resource(resource_data, partial=True, **kwargs)
        except (ResourceDeletionError, IntegrityError, Error, ValidationError):
            logger.exception(f"Failed to gracefully handle conflict for {resource_data}")
            return SyncResult(SyncStatus.CONFLICT, manifest_item)
    except (Error, ValidationError):
        # Something happened with the database. We don't know what it is. Instead of failing the whole
        # sync, we'll raise an error and skip this for now.
        logger.exception(f"Failed to update resource {resource.ansible_id}. Will try again on the next sync.")
        return SyncResult(SyncStatus.ERROR, manifest_item)

    return SyncResult(SyncStatus.UPDATED, manifest_item)


def _attempt_create_resource(
    manifest_item: ManifestItem,
    resource_data: dict,
    resource_type: ResourceType,
    resource_service_id: str,
    api_client: ResourceAPIClient,
) -> SyncResult:
    try:
        Resource.create_resource(
            resource_type=resource_type,
            resource_data=resource_data,
            ansible_id=manifest_item.ansible_id,
            service_id=resource_service_id,
        )
    except SkipResource:
        return SyncResult(SyncStatus.NOOP, manifest_item)
    except IntegrityError:
        # This typically means that there was a duplicate key error. To mitigate this
        # we will attempt to handle the conflicting resource and perform the operation
        # again.
        try:
            _handle_conflict(resource_data, resource_type, api_client)
            Resource.create_resource(
                resource_type=resource_type,
                resource_data=resource_data,
                ansible_id=manifest_item.ansible_id,
                service_id=resource_service_id,
            )
        except (ResourceDeletionError, IntegrityError, Error, ValidationError):
            logger.exception(f"Failed to gracefully handle conflict for {resource_data}")
            return SyncResult(SyncStatus.CONFLICT, manifest_item)
    except (Error, ValidationError):
        # Something happened with the database. We don't know what it is. Instead of failing the whole
        # sync, we'll raise an error and skip this for now.
        logger.exception(f"Failed to create {manifest_item.ansible_id}. Will try again on the next sync.")
        return SyncResult(SyncStatus.ERROR, manifest_item)

    return SyncResult(SyncStatus.CREATED, manifest_item)


def resource_sync(
    manifest_item: ManifestItem,
    api_client: ResourceAPIClient | None = None,
) -> SyncResult:
    """Uni-directional sync local resources from RESOURCE_SERVER resources."""
    api_client = api_client or create_api_client()
    local_managed_resource = get_managed_resource(manifest_item)
    resource_data = None
    resource_type_name = None
    resource_service_id = None
    unavailable = False  # for retry mechanism

    def set_resource_local_variables():
        """Inner caching function to avoid making unnecessary requests."""
        nonlocal resource_data
        nonlocal resource_type_name
        nonlocal resource_service_id
        nonlocal unavailable
        if resource_data is None or resource_type_name is None:
            resp = api_client.get_resource(manifest_item.ansible_id)
            if 400 <= resp.status_code < 500:  # pragma: no cover
                unavailable = True
                return
            resp.raise_for_status()
            resource_data = resp.json()["resource_data"]
            resource_type_name = resp.json()["resource_type"]
            resource_service_id = resp.json()["service_id"]

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
            api_client,
            service_id=resource_service_id,
        )
    else:
        # New: Create it locally
        set_resource_local_variables()
        if unavailable:  # pragma: no cover
            return SyncResult(SyncStatus.UNAVAILABLE, manifest_item)
        manifest_item.resource_data = resource_data
        resource_type = ResourceType.objects.get(name=resource_type_name)
        return _attempt_create_resource(
            manifest_item=manifest_item,
            resource_data=resource_data,
            resource_type=resource_type,
            resource_service_id=resource_service_id,
            api_client=api_client,
        )


# https://docs.djangoproject.com/en/4.2/topics/async/#asgiref.sync.sync_to_async
async_resource_sync = sync_to_async(resource_sync)


@dataclass
class SyncExecutor:
    """Public Executor Implementing Sync and Async process."""

    api_client: ResourceAPIClient = field(default_factory=create_api_client)
    resource_type_names: list[str] | None = None
    retries: int = 0
    retrysleep: int = 30
    stdout: TextIOBase | None = None
    unavailable: set = field(default_factory=set)
    attempts: int = 0
    deleted_count: int = 0
    asyncio: bool = False
    results: dict = field(default_factory=lambda: defaultdict(list))
    sync_assignments: bool = True
    page_size: int | None = None
    service_filter: str | None = None

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
        created_count = updated_count = conflicted_count = skipped_count = error_count = 0
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
            elif status == SyncStatus.ERROR:
                error_count += 1
            else:  # pragma: no cover
                raise TypeError("Unhandled SyncResult")

        self.write(
            f"Processed {len(results) + self.deleted_count} | "
            f"Created {created_count} | "
            f"Updated {updated_count} | "
            f"Conflict {conflicted_count} | "
            f"Unavailable {len(self.unavailable)} | "
            f"Skipped {skipped_count} | "
            f"Deleted {self.deleted_count} | "
            f"Errors {error_count}"
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
        orphan_count = resources_to_cleanup.count()
        deleted_before = len(self.results["deleted"])
        if orphan_count:
            self.write(f"Deleting {orphan_count} orphaned resources")
            for orphan in resources_to_cleanup:
                try:
                    _sc = orphan.content_type.resource_type.serializer_class
                    data = _sc(orphan.content_object).data
                    data.update(orphan.summary_fields())
                    with transaction.atomic():
                        delete_resource(orphan)
                except Exception as exc:
                    self.write(f"Error deleting orphaned resource {orphan.ansible_id}: {type(exc).__name__}: {exc}")
                else:  # persist in the report
                    self.results["deleted"].append(data)
        self.deleted_count = len(self.results["deleted"]) - deleted_before  # actual successes for this resource type

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
        """Sync all the items from the manifest using either asyncio or sequentially."""
        if self.asyncio is True:  # pragma: no cover
            self.write(f"Processing {len(manifest_list)} resources with asyncio executor.")
            self.write()
            asyncio.run(self._a_process_manifest_list(manifest_list))
        else:
            self.write(f"Processing {len(manifest_list)} resources sequentially.")
            self.write()
            self._process_manifest_list(manifest_list)

    def _apply_assignment_changes(self, assignment_set, action_fn, label):
        """Apply *action_fn* to each assignment in *assignment_set* and return (success_count, error_count)."""
        success_count = 0
        error_count = 0
        for assignment_tuple in assignment_set:
            if action_fn(assignment_tuple):
                success_count += 1
                self.write(
                    f"{label} assignment {assignment_tuple.assignment_type} {assignment_tuple.actor_ansible_id}"
                    f" -> {assignment_tuple.role_definition_name} on {assignment_tuple.ansible_id_or_pk or 'global'}"
                )
            else:
                error_count += 1
        return success_count, error_count

    def _sync_assignments(self):
        """Synchronize role assignments between local and remote systems."""
        if not self.sync_assignments:
            return

        if not is_rbac_installed():
            self.write(">>> Skipping role assignments sync (rbac not installed)")
            return

        self.write(">>> Syncing role assignments")

        try:
            remote_result = get_remote_assignments(self.api_client, page_size=self.page_size, service_filter=self.service_filter)
            local_assignments = get_local_assignments(service=self.service_filter)

            # Deletions are only safe when the remote fetch was complete.
            # A partial fetch would cause us to delete assignments that
            # simply weren't fetched.
            if remote_result.is_complete:
                to_delete = local_assignments - remote_result.assignments
                deleted_count, delete_errors = self._apply_assignment_changes(to_delete, delete_local_assignment, "DELETED")
            else:
                self.write("Skipping assignment deletions — remote fetch was incomplete. Will retry on next sync cycle.")
                logger.warning("Skipping assignment deletions: remote fetch was incomplete. Deletions deferred to next complete sync.")
                deleted_count, delete_errors = 0, 0

            # Creations are safe even on a partial fetch.
            to_create = remote_result.assignments - local_assignments
            created_count, create_errors = self._apply_assignment_changes(to_create, create_local_assignment, "CREATED")

            error_count = delete_errors + create_errors
            self.write(f"Assignment sync completed: Created {created_count} | Deleted {deleted_count} | Errors {error_count}")

            self.results["assignments_created"] = [created_count]
            self.results["assignments_deleted"] = [deleted_count]
            self.results["assignment_errors"] = [error_count]

        except Exception as e:
            self.write(f"Assignment sync failed: {e}")
            logger.exception("Assignment sync failed")

    def run(self):
        """Run the sync workflow.

        1. Iterate enabled resource types.
        2. Fetch RESOURCE_SERVER manifest.
        3. Cleanup orphaned resources (deleted remotely).
        4. Process the sync for each item in the manifest.
        5. Handle retries.
        6. Sync role assignments.
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

        # Sync assignments after all resources are synced
        self._sync_assignments()
        self.write()

        self.write("----- RESOURCE SYNC FINISHED -----")
