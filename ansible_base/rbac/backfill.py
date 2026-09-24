import logging

from django.db.models import Q

logger = logging.getLogger(__name__)


def backfill_object_ansible_id(apps, schema_editor=None):
    """Populate assignment resource IDs using app/model content type identity."""
    RoleUserAssignment = apps.get_model('dab_rbac', 'RoleUserAssignment')
    RoleTeamAssignment = apps.get_model('dab_rbac', 'RoleTeamAssignment')
    DABContentType = apps.get_model('dab_rbac', 'DABContentType')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    try:
        Resource = apps.get_model('dab_resource_registry', 'Resource')
    except LookupError:
        return

    db_alias = schema_editor.connection.alias if schema_editor else 'default'
    content_type_ids = set()
    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        content_type_ids.update(
            AssignmentModel.objects.using(db_alias)
            .filter(object_ansible_id__isnull=True, content_type_id__isnull=False)
            .values_list('content_type_id', flat=True)
            .distinct()
        )
    if not content_type_ids:
        return

    dab_types = {ct.id: ct for ct in DABContentType.objects.using(db_alias).filter(id__in=content_type_ids)}
    if not dab_types:
        return

    content_type_filter = Q()
    for ct in dab_types.values():
        content_type_filter |= Q(app_label=ct.app_label, model=ct.model)
    django_types = {(ct.app_label, ct.model): ct.id for ct in ContentType.objects.using(db_alias).filter(content_type_filter)}

    for AssignmentModel in (RoleUserAssignment, RoleTeamAssignment):
        assignments = list(
            AssignmentModel.objects.using(db_alias)
            .filter(object_ansible_id__isnull=True, content_type_id__in=dab_types, object_id__isnull=False)
            .only('pk', 'content_type_id', 'object_id')
        )
        resource_filters = Q()
        for assignment in assignments:
            dab_type = dab_types[assignment.content_type_id]
            django_type_id = django_types.get((dab_type.app_label, dab_type.model))
            if django_type_id:
                resource_filters |= Q(content_type_id=django_type_id, object_id=assignment.object_id)

        if not resource_filters:
            continue

        resource_ids = {
            (resource.content_type_id, resource.object_id): resource.ansible_id
            for resource in Resource.objects.using(db_alias).filter(resource_filters).only('content_type_id', 'object_id', 'ansible_id')
        }
        updates = []
        for assignment in assignments:
            dab_type = dab_types[assignment.content_type_id]
            django_type_id = django_types.get((dab_type.app_label, dab_type.model))
            ansible_id = resource_ids.get((django_type_id, assignment.object_id))
            if ansible_id is not None:
                assignment.object_ansible_id = ansible_id
                updates.append(assignment)
        if updates:
            AssignmentModel.objects.using(db_alias).bulk_update(updates, ['object_ansible_id'])
            logger.info('Backfilled object_ansible_id on %d %s rows.', len(updates), AssignmentModel.__name__)
