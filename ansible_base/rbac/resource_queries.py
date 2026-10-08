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

    if resource_model is None:
        from ansible_base.resource_registry.models import Resource

        resource_model = Resource

    resource_manager = resource_model.objects.db_manager(using) if using else resource_model.objects
    lookup_terms = []
    for content_type_key, object_ids in local_types.items():
        object_ids = tuple(object_ids)
        for start in range(0, len(object_ids), RESOURCE_LOOKUP_BATCH_SIZE):
            lookup_terms.append((content_type_key, object_ids[start : start + RESOURCE_LOOKUP_BATCH_SIZE]))

    resource_ids = {}
    term_batch = []
    term_object_count = 0
    for term in lookup_terms:
        if term_batch and term_object_count + len(term[1]) > RESOURCE_LOOKUP_BATCH_SIZE:
            resource_ids.update(_fetch_resource_ids(resource_manager, term_batch))
            term_batch = []
            term_object_count = 0
        term_batch.append(term)
        term_object_count += len(term[1])
    if term_batch:
        resource_ids.update(_fetch_resource_ids(resource_manager, term_batch))
    return resource_ids


def _fetch_resource_ids(resource_manager, terms):
    if len(terms) == 1:
        content_type_key, object_ids = terms[0]
        rows = resource_manager.filter(
            **resource_content_type_identity_filter(*content_type_key),
            object_id__in=object_ids,
        ).values('content_type__app_label', 'content_type__model', 'object_id', 'ansible_id')
    else:
        resource_filter = Q()
        for content_type_key, object_ids in terms:
            resource_filter |= Q(
                **resource_content_type_identity_filter(*content_type_key),
                object_id__in=object_ids,
            )
        rows = resource_manager.filter(resource_filter).values('content_type__app_label', 'content_type__model', 'object_id', 'ansible_id')
    return {(row['content_type__app_label'], row['content_type__model'], row['object_id']): str(row['ansible_id']) for row in rows}


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
