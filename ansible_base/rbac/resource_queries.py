from collections.abc import Collection, Mapping

from django.db.models import Case, OuterRef, Q, Subquery, When

from .remote import get_local_resource_services

RESOURCE_LOOKUP_BATCH_SIZE = 1000


def resource_content_type_identity_filter(app_label, model):
    """Return the Resource content-type predicates for a DAB model identity."""
    return {
        'content_type__app_label': app_label,
        'content_type__model': model,
    }


def resolve_resource_ids(
    object_ids_by_type: Mapping[tuple[str, str], Collection[str]],
    services_by_type: Mapping[tuple[str, str], Collection[str]],
    using=None,
    content_type_model=None,
    resource_model=None,
) -> dict[tuple[str, str, str], str]:
    """Resolve local Resource IDs for bounded sets of app/model/object IDs."""
    local_services = set(get_local_resource_services())
    local_types = {
        content_type: object_ids
        for content_type, object_ids in object_ids_by_type.items()
        if local_services.intersection(services_by_type.get(content_type, ()))
    }
    if not local_types:
        return {}

    if content_type_model is None:
        from django.contrib.contenttypes.models import ContentType

        content_type_model = ContentType

    content_type_filter = Q()
    for (app_label, model), _object_ids in local_types.items():
        content_type_filter |= Q(app_label=app_label, model=model)
    content_type_manager = content_type_model.objects.db_manager(using) if using else content_type_model.objects
    django_content_types = list(content_type_manager.filter(content_type_filter).values('id', 'app_label', 'model'))
    if not django_content_types:
        return {}

    if resource_model is None:
        from ansible_base.resource_registry.models import Resource

        resource_model = Resource

    resource_manager = resource_model.objects.db_manager(using) if using else resource_model.objects
    resource_ids = {}
    for content_type in django_content_types:
        content_type_key = (content_type['app_label'], content_type['model'])
        object_ids = tuple(local_types[content_type_key])
        for start in range(0, len(object_ids), RESOURCE_LOOKUP_BATCH_SIZE):
            rows = resource_manager.filter(
                **resource_content_type_identity_filter(*content_type_key),
                object_id__in=object_ids[start : start + RESOURCE_LOOKUP_BATCH_SIZE],
            ).values('content_type__app_label', 'content_type__model', 'object_id', 'ansible_id')
            resource_ids.update({(row['content_type__app_label'], row['content_type__model'], row['object_id']): str(row['ansible_id']) for row in rows})
    return resource_ids


def assignment_resource_annotation(field_name):
    """Annotate an assignment with metadata from its matching Resource."""
    # Import lazily because resource_registry is an optional app for RBAC.
    from ansible_base.resource_registry.models import Resource

    resource = Resource.objects.filter(
        object_id=OuterRef('object_id'),
        **resource_content_type_identity_filter(OuterRef('content_type__app_label'), OuterRef('content_type__model')),
    ).values(field_name)[:1]

    return Case(
        When(content_type__service__in=get_local_resource_services(), then=Subquery(resource)),
        default=None,
        output_field=Resource._meta.get_field(field_name),
    )
