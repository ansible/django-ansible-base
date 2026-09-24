import logging

from django.db import router

from ansible_base.rbac.remote import get_local_resource_services
from ansible_base.rbac.resource_queries import resolve_resource_ids

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def _backfill_batch(AssignmentModel, rows, dab_types, using, content_type_model, resource_model):
    object_ids_by_type = {}
    services_by_type = {}
    for row in rows:
        dab_type = dab_types.get(row['content_type_id'])
        if dab_type is None:
            continue
        content_type_key = (dab_type.app_label, dab_type.model)
        object_ids_by_type.setdefault(content_type_key, set()).add(row['object_id'])
        services_by_type.setdefault(content_type_key, set()).add(dab_type.service)

    resource_ids = resolve_resource_ids(
        object_ids_by_type,
        services_by_type,
        using=using,
        content_type_model=content_type_model,
        resource_model=resource_model,
    )
    updates = []
    for row in rows:
        dab_type = dab_types.get(row['content_type_id'])
        if dab_type is None:
            continue
        resource_id = resource_ids.get((dab_type.app_label, dab_type.model, row['object_id']))
        if resource_id is not None:
            updates.append(AssignmentModel(pk=row['pk'], object_ansible_id=resource_id))

    if updates:
        AssignmentModel.objects.using(using).bulk_update(updates, ['object_ansible_id'], batch_size=BATCH_SIZE)
        logger.info('Backfilled object_ansible_id on %d %s rows.', len(updates), AssignmentModel.__name__)


def backfill_object_ansible_id(apps, schema_editor=None, using=None):
    """Populate assignment resource IDs using bounded app/model lookups."""
    RoleUserAssignment = apps.get_model('dab_rbac', 'RoleUserAssignment')
    RoleTeamAssignment = apps.get_model('dab_rbac', 'RoleTeamAssignment')
    DABContentType = apps.get_model('dab_rbac', 'DABContentType')

    try:
        Resource = apps.get_model('dab_resource_registry', 'Resource')
    except LookupError:
        return
    ContentType = apps.get_model('contenttypes', 'ContentType')

    local_services = set(get_local_resource_services())
    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        db_alias = using or (schema_editor.connection.alias if schema_editor else router.db_for_write(AssignmentModel))
        content_type_ids = set(
            AssignmentModel.objects.using(db_alias)
            .filter(object_ansible_id__isnull=True, content_type_id__isnull=False)
            .values_list('content_type_id', flat=True)
            .distinct()
        )
        if not content_type_ids:
            continue

        dab_types = {ct.id: ct for ct in DABContentType.objects.using(db_alias).filter(id__in=content_type_ids, service__in=local_services)}
        if not dab_types:
            continue

        rows = (
            AssignmentModel.objects.using(db_alias)
            .filter(object_ansible_id__isnull=True, content_type_id__in=dab_types, object_id__isnull=False)
            .order_by('pk')
            .values('pk', 'content_type_id', 'object_id')
            .iterator(chunk_size=BATCH_SIZE)
        )
        batch = []
        for row in rows:
            batch.append(row)
            if len(batch) == BATCH_SIZE:
                _backfill_batch(AssignmentModel, batch, dab_types, db_alias, ContentType, Resource)
                batch.clear()
        if batch:
            _backfill_batch(AssignmentModel, batch, dab_types, db_alias, ContentType, Resource)
