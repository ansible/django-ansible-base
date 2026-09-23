from django.db.models import Case, OuterRef, Subquery, When

from ansible_base.resource_registry.models import Resource

from .remote import get_local_resource_prefix


def assignment_resource_annotation(field_name):
    """Annotate an assignment with metadata from its matching Resource."""
    resource = Resource.objects.filter(
        object_id=OuterRef('object_id'),
        content_type__app_label=OuterRef('content_type__app_label'),
        content_type__model=OuterRef('content_type__model'),
    ).values(field_name)[:1]

    return Case(
        When(content_type__service__in=('shared', get_local_resource_prefix()), then=Subquery(resource)),
        default=None,
        output_field=Resource._meta.get_field(field_name),
    )
