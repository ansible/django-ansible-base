import logging

logger = logging.getLogger(__name__)

UUID_REGEX = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'


def repair_assignment_corruption(apps, schema_editor=None):
    """
    Delete corrupt RBAC assignments created by the PR-1093 cross-table content-type
    ID collision bug.

    The bug: AssignmentResourceField joined assignment.content_type_id (DABContentType PK)
    against resource.content_type_id (Django ContentType PK). These sequences are
    independent, so IDs collide by coincidence. Cross-service sync used the wrong
    ansible_id from this join, then stored the wrong resource's object_id on the
    receiving side — producing a UUID in object_id under a content type that expects
    an integer PK.

    Detection: object_id matches UUID pattern AND content type pk_field_type is not 'uuid'.
    Fix: delete — we cannot reliably reconstruct the intended target.

    Pass django.apps.apps when calling outside of a migration.
    """
    RoleUserAssignment = apps.get_model('dab_rbac', 'RoleUserAssignment')
    RoleTeamAssignment = apps.get_model('dab_rbac', 'RoleTeamAssignment')

    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        # Exclude 'uuid' rather than matching 'integer': integer-PK fields report
        # 'serial'/'bigserial' on PostgreSQL but 'integer' on SQLite.
        deleted, _ = AssignmentModel.objects.filter(object_id__iregex=UUID_REGEX).exclude(content_type__pk_field_type='uuid').delete()
        if deleted:
            logger.warning(
                "Deleted %d corrupt %s assignments (UUID object_id with non-UUID-PK content type)",
                deleted,
                AssignmentModel.__name__,
            )


def backfill_object_ansible_id(apps, schema_editor=None):
    """
    Populate object_ansible_id on assignments where it is NULL.

    Bridges DABContentType → Django ContentType by (app_label, model), then
    queries Resource for the ansible_id of each assigned object.

    Pass django.apps.apps when calling outside of a migration.
    """
    RoleUserAssignment = apps.get_model('dab_rbac', 'RoleUserAssignment')
    RoleTeamAssignment = apps.get_model('dab_rbac', 'RoleTeamAssignment')
    DABContentType = apps.get_model('dab_rbac', 'DABContentType')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    try:
        Resource = apps.get_model('dab_resource_registry', 'Resource')
    except LookupError:
        return  # resource_registry not installed — nothing to backfill from

    django_ct_by_key = {(ct.app_label, ct.model): ct for ct in ContentType.objects.all()}

    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        null_qs = AssignmentModel.objects.filter(
            object_ansible_id__isnull=True,
            content_type_id__isnull=False,
            object_id__isnull=False,
        )
        for dab_ct_id in null_qs.values_list('content_type_id', flat=True).distinct():
            try:
                dab_ct = DABContentType.objects.get(pk=dab_ct_id)
            except DABContentType.DoesNotExist:
                continue

            django_ct = django_ct_by_key.get((dab_ct.app_label, dab_ct.model))
            if django_ct is None:
                continue  # remote type — no local Resource

            assignments = list(null_qs.filter(content_type_id=dab_ct_id))
            resource_map = {
                r['object_id']: r['ansible_id']
                for r in Resource.objects.filter(
                    content_type_id=django_ct.id,
                    object_id__in={a.object_id for a in assignments},
                ).values('object_id', 'ansible_id')
            }

            to_update = [a for a in assignments if a.object_id in resource_map]
            for a in to_update:
                a.object_ansible_id = resource_map[a.object_id]
            if to_update:
                AssignmentModel.objects.bulk_update(to_update, ['object_ansible_id'])
