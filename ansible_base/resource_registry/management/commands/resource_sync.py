"""
Command to sync resources from RESOURCE_SERVER to local services
Each service must execute this command manually or scheduled.

Alternatively each service can use the functions implemented on
resource_registry.tasks module to spawn syncs in a task queue.

Usage::

    django-admin resource_sync  # sync all resources

Optional resource type name argument::

    django-admin resource_sync user  # only shared.user
    django-admin resource_sync shared.user  # the same
    django-admin resource_sync user organization team  # shared. prefix will be handled

Optional parameters::

    `--retries number` to retry failed syncs
    `--retrysleep seconds` to set interval between retries
    `--asyncio` Flag to enable asyncio executor
"""

from django.core.management.base import BaseCommand, CommandError

from ansible_base.resource_registry.tasks.sync import ResourceSyncHTTPError, SyncExecutor, get_resource_type_names


def valid_resource_type(resource_type):  # pragma: no cover
    resource_type = resource_type.strip()
    if not resource_type.startswith("shared."):
        resource_type = f"shared.{resource_type}"
    valid_options = get_resource_type_names()
    if resource_type not in valid_options:
        raise CommandError(f"Invalid resource_type {resource_type}, options are {valid_options}")
    return resource_type


class Command(BaseCommand):  # pragma: no cover
    help = "Fetch Resource State from RESOURCE_PROVIDER and sync with local service."

    def add_arguments(self, parser):
        parser.add_argument(
            "resource_type_names",
            nargs="*",
            type=valid_resource_type,
            help="Optional, one or more names e.g: `shared.user` or `shared.user shared.organization`",
        )
        parser.add_argument(
            "--retries",
            type=int,
            default=3,
            help="For when a resource is unavailable, how many retries to perform",
            required=False,
        )
        parser.add_argument(
            "--retrysleep",
            type=int,
            default=30,
            help="Interval between retries",
            required=False,
        )
        parser.add_argument("--asyncio", action="store_true", default=False, help="Enable asyncio executor")
        parser.add_argument(
            "--page-size",
            type=int,
            default=None,
            dest="page_size",
            help="Page size for pagination when fetching assignments (default: from settings, capped server-side by MAX_PAGE_SIZE)",
            required=False,
        )

    def handle(self, *args, **options):
        """Handle RESOURCE_PROVIDER sync"""
        if options.get("page_size") is not None and options["page_size"] < 1:
            raise CommandError("--page-size must be at least 1")
        arguments = ["resource_type_names", "retries", "retrysleep", "asyncio", "page_size"]
        options = {k: v for k, v in options.items() if k in arguments}
        try:
            executor = SyncExecutor(**options, stdout=self.stdout)
            executor.run()
        except ResourceSyncHTTPError as exc:
            raise CommandError(f"Error accessing Resource Server: {str(exc)}")

        # NOTE: Can optionally take --report-json and then serialize executor.results
