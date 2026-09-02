import logging
import re

logger = logging.getLogger(__name__)

UUID_REGEX = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'


def _matches_pk_type(object_id, pk_field_type):
    if pk_field_type == 'uuid':
        return bool(re.match(UUID_REGEX, object_id, re.IGNORECASE))
    return object_id.isdigit()


def repair_assignment_corruption(apps, schema_editor=None):
    """
    Delete RBAC assignments that reference objects which do not exist.

    For each object-scoped assignment, verifies that the referenced object
    actually exists in the model's table. Assignments are corrupt when:
    - object_id does not match the expected PK format for the content type
      (e.g. a UUID string under an integer-PK model), or
    - object_id is the right format but no such object exists in the table.

    Remote content types (not present in INSTALLED_APPS) are skipped — we
    cannot query a table that is not local.

    Pass django.apps.apps when calling outside of a migration.
    """
    RoleUserAssignment = apps.get_model('dab_rbac', 'RoleUserAssignment')
    RoleTeamAssignment = apps.get_model('dab_rbac', 'RoleTeamAssignment')
    DABContentType = apps.get_model('dab_rbac', 'DABContentType')

    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        scoped_qs = AssignmentModel.objects.filter(
            content_type_id__isnull=False,
            object_id__isnull=False,
        )
        for dab_ct_id in scoped_qs.values_list('content_type_id', flat=True).distinct():
            try:
                dab_ct = DABContentType.objects.get(pk=dab_ct_id)
            except DABContentType.DoesNotExist:
                continue

            try:
                model = apps.get_model(dab_ct.app_label, dab_ct.model)
            except LookupError:
                continue  # remote model — cannot verify

            ct_assignments = list(scoped_qs.filter(content_type_id=dab_ct_id))

            wrong_format = [a for a in ct_assignments if not _matches_pk_type(a.object_id, dab_ct.pk_field_type)]
            right_format = [a for a in ct_assignments if _matches_pk_type(a.object_id, dab_ct.pk_field_type)]

            existing_pks = set(
                str(pk)
                for pk in model.objects.filter(
                    pk__in={a.object_id for a in right_format}
                ).values_list('pk', flat=True)
            )
            not_found = [a for a in right_format if a.object_id not in existing_pks]

            corrupt_pks = [a.pk for a in wrong_format + not_found]
            if corrupt_pks:
                deleted, _ = AssignmentModel.objects.filter(pk__in=corrupt_pks).delete()
                logger.warning(
                    "Deleted %d corrupt %s assignments for content type %s.%s",
                    deleted,
                    AssignmentModel.__name__,
                    dab_ct.app_label,
                    dab_ct.model,
                )
