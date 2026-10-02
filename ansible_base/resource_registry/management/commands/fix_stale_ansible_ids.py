"""
Audit and repair stale ansible_id references in the resource registry.

After a 2.4→2.6 upgrade, the gateway and controller initialize independent
resource registries with different ansible_id values for the same teams/orgs.
If resource_sync doesn't fully converge the registries, teams can end up in
a "frozen state" where role assignments can't be created, deleted, or synced.

This command detects and fixes two problems:
  1. Model instances (teams, orgs) missing their Resource entry entirely
  2. Duplicate Resource entries for the same model instance (gateway side)

Usage::

    awx-manage fix_stale_ansible_ids                    # audit all types
    awx-manage fix_stale_ansible_ids team organization  # audit specific types
    awx-manage fix_stale_ansible_ids --fix              # create missing entries
    awx-manage fix_stale_ansible_ids --fix-duplicates   # consolidate duplicates
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from ansible_base.resource_registry.models import Resource, ResourceType, init_resource_from_object

logger = logging.getLogger("ansible_base.resource_registry.fix_stale_ansible_ids")


class Command(BaseCommand):
    help = (
        "Audit and repair stale ansible_id references in the resource registry. "
        "Detects missing Resource entries and duplicate entries that cause "
        "role assignment sync failures after 2.4→2.6 upgrades."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "resource_types",
            nargs="*",
            help="Resource type names to process (e.g., team organization). Default: all registered types.",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Create missing Resource entries. Without this flag, only reports findings.",
        )
        parser.add_argument(
            "--fix-duplicates",
            action="store_true",
            dest="fix_duplicates",
            help="Remove duplicate Resource entries, keeping the one with the lowest pk.",
        )

    def _resolve_resource_types(self, requested_types):
        resource_types = ResourceType.objects.all()
        if not requested_types:
            return resource_types

        normalized = []
        for rt in requested_types:
            if not rt.startswith("shared."):
                rt = f"shared.{rt}"
            normalized.append(rt)
        matched = resource_types.filter(name__in=normalized)
        matched_names = set(matched.values_list("name", flat=True))
        unmatched = set(normalized) - matched_names
        if unmatched:
            raise CommandError(f"Unknown resource type(s): {', '.join(sorted(unmatched))}")
        return matched

    def handle(self, *args, **options):
        fix = options["fix"]
        fix_duplicates = options["fix_duplicates"]

        resource_types = self._resolve_resource_types(options["resource_types"])
        if not resource_types.exists():
            self.stderr.write("No matching resource types found.")
            return

        total_missing = 0
        total_created = 0
        total_duplicates = 0
        total_duplicates_removed = 0
        total_orphans = 0

        for rt in resource_types:
            missing, created, duplicates, duplicates_removed, orphans = self._process_resource_type(rt, fix=fix, fix_duplicates=fix_duplicates)
            total_missing += missing
            total_created += created
            total_duplicates += duplicates
            total_duplicates_removed += duplicates_removed
            total_orphans += orphans

        self._print_summary(total_missing, total_created, total_duplicates, total_duplicates_removed, total_orphans, fix, fix_duplicates)

    def _print_summary(self, total_missing, total_created, total_duplicates, total_duplicates_removed, total_orphans, fix, fix_duplicates):
        self.stdout.write("")
        if total_missing == 0 and total_duplicates == 0 and total_orphans == 0:
            self.stdout.write(self.style.SUCCESS("All resource types OK."))
            return

        if total_missing > 0:
            if fix:
                self.stdout.write(self.style.SUCCESS(f"Created {total_created} missing Resource entries."))
                self.stdout.write(
                    "Next: run 'awx-manage resource_sync team organization' to align ansible_ids with the gateway, then re-run the role assignment sync."
                )
            else:
                self.stdout.write(self.style.WARNING(f"{total_missing} missing Resource entries. Run with --fix to create them."))
        if total_duplicates > 0:
            if fix_duplicates:
                self.stdout.write(self.style.SUCCESS(f"Removed {total_duplicates_removed} duplicate Resource entries."))
            else:
                self.stdout.write(self.style.WARNING(f"{total_duplicates} duplicate Resource entries. Run with --fix-duplicates to consolidate."))
        if total_orphans > 0:
            self.stdout.write(
                self.style.WARNING(f"{total_orphans} orphan Resource entries (no model instance). These are harmless but indicate prior sync issues.")
            )

    def _process_resource_type(self, rt, fix=False, fix_duplicates=False):
        ct = rt.content_type
        model_cls = ct.model_class()
        if model_cls is None:
            self.stderr.write(f"Skipping {rt.name}: model class not found")
            return 0, 0, 0, 0, 0

        resource_config = rt.get_resource_config()
        self.stdout.write(f"\n--- {rt.name} ---")

        existing_resource_ids = set(Resource.objects.filter(content_type=ct).values_list("object_id", flat=True))
        all_pk_strs = {str(pk) for pk in model_cls.objects.values_list("pk", flat=True)}

        missing_pks = all_pk_strs - existing_resource_ids
        orphan_pks = existing_resource_ids - all_pk_strs

        self.stdout.write(f"  Instances: {len(all_pk_strs)}, Resource entries: {len(existing_resource_ids)}")

        # --- Missing entries ---
        created = 0
        if missing_pks:
            self.stdout.write(self.style.WARNING(f"  Missing Resource entries: {len(missing_pks)}"))
            if fix:
                created = self._create_missing_entries(model_cls, missing_pks, rt, resource_config)
                self.stdout.write(self.style.SUCCESS(f"  Created {created} Resource entries"))
            else:
                self._report_sample(model_cls, missing_pks)
        else:
            self.stdout.write(self.style.SUCCESS("  All instances have Resource entries"))

        # --- Orphan entries ---
        if orphan_pks:
            self.stdout.write(self.style.WARNING(f"  Orphan Resource entries (no instance): {len(orphan_pks)}"))

        # --- Duplicate entries ---
        duplicates_found, duplicates_removed = self._check_duplicates(ct, fix_duplicates)

        return len(missing_pks), created, duplicates_found, duplicates_removed, len(orphan_pks)

    def _create_missing_entries(self, model_cls, missing_pks, rt, resource_config):
        coerced_pks = []
        for pk in missing_pks:
            try:
                coerced_pks.append(int(pk))
            except ValueError:  # pragma: no cover — UUID primary keys
                coerced_pks.append(pk)

        batch = []
        created = 0
        for obj in model_cls.objects.filter(pk__in=coerced_pks).iterator(chunk_size=500):
            batch.append(init_resource_from_object(obj, resource_type=rt, resource_config=resource_config))
            if len(batch) >= 500:  # pragma: no cover
                Resource.objects.bulk_create(batch, ignore_conflicts=True)
                created += len(batch)
                batch.clear()
        if batch:
            Resource.objects.bulk_create(batch, ignore_conflicts=True)
            created += len(batch)
        return created

    def _report_sample(self, model_cls, pks, limit=10):
        coerced = []
        for pk in list(pks)[:limit]:
            try:
                coerced.append(int(pk))
            except ValueError:  # pragma: no cover — UUID primary keys
                coerced.append(pk)
        for obj in model_cls.objects.filter(pk__in=coerced):
            name = getattr(obj, "name", str(obj))
            self.stdout.write(f"    {name} (pk={obj.pk})")
        remaining = len(pks) - limit
        if remaining > 0:
            self.stdout.write(f"    ... and {remaining} more")

    def _check_duplicates(self, ct, fix_duplicates):
        dupes = list(Resource.objects.filter(content_type=ct).values("object_id").annotate(entry_count=Count("id")).filter(entry_count__gt=1))

        dupe_count = len(dupes)
        if dupe_count == 0:
            return 0, 0

        self.stdout.write(self.style.ERROR(f"  DUPLICATE Resource entries: {dupe_count} instances have multiple entries"))

        removed = 0
        for i, dupe in enumerate(dupes):
            entries = Resource.objects.filter(content_type=ct, object_id=dupe["object_id"]).order_by("pk")

            if i < 10:
                ids_list = list(entries.values_list("ansible_id", flat=True))
                self.stdout.write(f"    object_id={dupe['object_id']}: {dupe['entry_count']} entries, ansible_ids={ids_list}")

            if fix_duplicates:
                keep = entries.first()
                to_delete = entries.exclude(pk=keep.pk)
                delete_count = to_delete.count()
                to_delete.delete()
                removed += delete_count
                if i < 10:
                    self.stdout.write(f"      Kept ansible_id={keep.ansible_id}, removed {delete_count} duplicates")

        if dupe_count > 10:  # pragma: no cover
            self.stdout.write(f"    ... and {dupe_count - 10} more")

        return dupe_count, removed
