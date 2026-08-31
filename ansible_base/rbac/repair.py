import logging

logger = logging.getLogger(__name__)

UUID_REGEX = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'


def repair_assignment_corruption(apps=None, schema_editor=None):
    """
    Repair corrupt RBAC assignments created by the PR-1093 cross-table content-type
    ID collision bug, and backfill the object_ansible_id denormalized field.

    Two operations:
    1. Delete assignments whose content type expects an integer PK but whose
       object_id is a UUID string — these were corrupted by a wrong JOIN that
       returned a RoleDefinition Resource's ansible_id as the object_id.
    2. Populate object_ansible_id on all remaining assignments by joining through
       Resource using (app_label, model) to bridge DABContentType → Django ContentType.

    Can be called from a Django migration (pass apps + schema_editor) or standalone
    (omit both arguments — uses the live models instead of historical ones).
    """
    from django.contrib.contenttypes.models import ContentType

    if apps is not None:
        RoleUserAssignment = apps.get_model('dab_rbac', 'RoleUserAssignment')
        RoleTeamAssignment = apps.get_model('dab_rbac', 'RoleTeamAssignment')
        DABContentType = apps.get_model('dab_rbac', 'DABContentType')
        try:
            Resource = apps.get_model('dab_resource_registry', 'Resource')
        except LookupError:
            Resource = None
    else:
        from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment
        from ansible_base.rbac.models.content_type import DABContentType

        try:
            from ansible_base.resource_registry.models import Resource
        except ImportError:
            Resource = None

    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        # Step 1: delete corrupt assignments — UUID object_id on a non-UUID pk type.
        # Exclude 'uuid' rather than matching 'integer' because integer-PK fields
        # report 'serial'/'bigserial' on PostgreSQL, 'integer' on SQLite.
        deleted, _ = (
            AssignmentModel.objects.filter(
                object_id__iregex=UUID_REGEX,
            )
            .exclude(
                content_type__pk_field_type='uuid',
            )
            .delete()
        )
        if deleted:
            logger.warning(
                "Deleted %d corrupt %s assignments (UUID object_id with integer-PK content type)",
                deleted,
                AssignmentModel.__name__,
            )

    if Resource is None:
        return  # resource_registry not installed — no Resources to backfill from

    django_ct_by_key = {(ct.app_label, ct.model): ct for ct in ContentType.objects.all()}

    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        # Step 2: backfill object_ansible_id via model-name bridge
        assignments_by_ct = {}
        for a in AssignmentModel.objects.filter(
            object_ansible_id__isnull=True,
            content_type_id__isnull=False,
            object_id__isnull=False,
        ).iterator():
            assignments_by_ct.setdefault(a.content_type_id, []).append(a)

        for dab_ct_id, assignments in assignments_by_ct.items():
            try:
                dab_ct = DABContentType.objects.get(pk=dab_ct_id)
            except DABContentType.DoesNotExist:
                continue

            django_ct = django_ct_by_key.get((dab_ct.app_label, dab_ct.model))
            if django_ct is None:
                continue  # remote type — no local Resource

            object_ids = {a.object_id for a in assignments}
            resource_map = {
                r.object_id: r.ansible_id
                for r in Resource.objects.filter(
                    content_type_id=django_ct.id,
                    object_id__in=object_ids,
                )
            }

            to_update = []
            for a in assignments:
                if a.object_id in resource_map:
                    a.object_ansible_id = resource_map[a.object_id]
                    to_update.append(a)

            if to_update:
                AssignmentModel.objects.bulk_update(to_update, ['object_ansible_id'])
