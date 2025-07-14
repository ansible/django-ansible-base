import uuid

from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend

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
                queryset = queryset.filter(object_role__content_type=resource_obj.content_type, object_role__object_id=resource_obj.object_id)
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
