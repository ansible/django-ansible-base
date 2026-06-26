import uuid

from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend

from ansible_base.rbac.models import DABContentType
from ansible_base.resource_registry.models import Resource


class AnsibleIdAliasFilterBackend(BaseFilterBackend):
    '''
    Filter backend for object_ansible_id.
    Note that this accrues an additional query to the Resource model.

    Example:
    /api/v1/role_user_assignments/?object_ansible_id=da0488f5-013b-460c-8a62-c3c10a1d0fad
    '''

    def filter_queryset(self, request, queryset, view):
        object_ansible_id = request.query_params.get('object_ansible_id')
        if object_ansible_id:
            try:
                # Validate if the provided ansible_id is a valid UUID
                uuid.UUID(object_ansible_id)
            except ValueError:
                raise ValidationError(f"Invalid UUID format for object_ansible_id: {object_ansible_id}")

            try:
                # Find the Resource object by its ansible_id
                resource_obj = Resource.objects.get(ansible_id=object_ansible_id)

                # Filter the queryset based on the resource's content_type and object_id
                ct = DABContentType.objects.get_for_model(resource_obj.content_type.model_class())
                queryset = queryset.filter(object_role__content_type=ct, object_role__object_id=resource_obj.object_id)
            except Resource.DoesNotExist:
                # If the resource is not found, return an empty queryset
                return queryset.none()

        return queryset


class UserAnsibleIdAliasFilterBackend(AnsibleIdAliasFilterBackend):
    """
    Filter backend for user_ansible_id and object_ansible_id.

    Example:
    /api/v1/role_user_assignments/?user_ansible_id=80c7e291-b121-48fc-8fb1-174aac6f57a6
    /api/v1/role_user_assignments/?object_ansible_id=da0488f5-013b-460c-8a62-c3c10a1d0fad
    """

    def filter_queryset(self, request, queryset, view):
        user_ansible_id = request.query_params.get('user_ansible_id')
        if user_ansible_id:
            try:
                # Validate if the provided ansible_id is a valid UUID
                uuid.UUID(user_ansible_id)
            except ValueError:
                raise ValidationError(f"Invalid UUID format for user_ansible_id: {user_ansible_id}")
            # Filter the queryset based on the user's ansible_id
            queryset = queryset.filter(user__resource__ansible_id=user_ansible_id)
        return super().filter_queryset(request, queryset, view)


class TeamAnsibleIdAliasFilterBackend(AnsibleIdAliasFilterBackend):
    """
    Filter backend for team_ansible_id and object_ansible_id.

    Example:
    /api/v1/role_team_assignments/?team_ansible_id=c2b59b42-a874-43ca-9e1f-abe410864f65
    /api/v1/role_team_assignments/?object_ansible_id=da0488f5-013b-460c-8a62-c3c10a1d0fad
    """

    def filter_queryset(self, request, queryset, view):
        team_ansible_id = request.query_params.get('team_ansible_id')
        if team_ansible_id:
            try:
                # Validate if the provided ansible_id is a valid UUID
                uuid.UUID(team_ansible_id)
            except ValueError:
                raise ValidationError(f"Invalid UUID format for team_ansible_id: {team_ansible_id}")
            # Filter the queryset based on the team's ansible_id
            queryset = queryset.filter(team__resource__ansible_id=team_ansible_id)
        return super().filter_queryset(request, queryset, view)


class ServiceFilterBackend(BaseFilterBackend):
    """
    Filter backend for content_type__service on role assignment endpoints.

    When the ``content_type__service`` query parameter is provided, returns
    only assignments whose content type belongs to the requested service,
    plus global assignments (``content_type IS NULL``).  Without the
    parameter all assignments are returned (backward compatible).

    Example:
    /api/v1/role_user_assignments/?content_type__service=controller
    """

    def filter_queryset(self, request, queryset, view):
        service = request.query_params.get('content_type__service')
        if service:
            queryset = queryset.filter(Q(content_type__service=service) | Q(content_type_id__isnull=True))
        return queryset


class RoleAssignmentFilterBackend(BaseFilterBackend):
    """
    Filter backend for listing a specific set of role (user or team) assignments.

    For cross-component coordination, we want to avoid filtering by the primary key.
    This allows returning records that matche a list of tuples.

    Example:
    /api/v1/role_user_assignments/?assignment=joe,Inventory%20Admin,42

    This would return the role assignment that user joe has to the inventory pk=42,
    if it exists.
    Crucially, this will OR multiple entries so you can get multiple items
    in a single request.

    Example:
    /api/v1/role_user_assignments/?assignment=joe,Inventory%20Admin,42&assignment=joe,Project%20Admin,9
    """

    def filter_queryset(self, request, queryset, view):
        raw_filters = request.query_params.getlist("assignment")
        q_objects = []

        view_model = queryset.model._meta.model_name

        for raw in raw_filters:
            actor_ansible_id, role_name, object_id = raw.split(",", 2)
            if '.' in object_id:
                raise ValidationError(f"Each filter must have exactly 3 values: {raw!r}")

            try:
                # Validate if the provided actor specifier is a valid UUID
                uuid.UUID(actor_ansible_id)
            except ValueError:
                raise ValidationError(f"Invalid UUID format for first part of assignment filter: {actor_ansible_id}")

            if view_model == 'roleuserassignment':
                this_q = Q(user__resource__ansible_id=actor_ansible_id, role_definition__name=role_name, object_id=object_id)
            elif view_model == 'roleteamassignment':
                this_q = Q(team__resource__ansible_id=actor_ansible_id, role_definition__name=role_name, object_id=object_id)
            else:
                raise RuntimeError('RoleAssignmentFilterBackend only valid for assignment views')

            q_objects.append(this_q)

        if q_objects:
            query = q_objects[0]
            for q in q_objects[1:]:
                query |= q
            queryset = queryset.filter(query)

        return queryset
