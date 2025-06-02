from rest_framework.filters import BaseFilterBackend
from ansible_base.resource_registry.models import Resource
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.contenttypes.models import ContentType

class AnsibleIdAliasFilterBackend(BaseFilterBackend):
    '''
    Filter backend for object ansible_id.
    Note that this accrues an additional query to the Resource model.

    Example:
    /api/v1/role_user_assignments/?object_ansible_id=da0488f5-013b-460c-8a62-c3c10a1d0fad
    '''
    def filter_queryset(self, request, queryset, view):
        object_ansible_id = request.query_params.get('object_ansible_id')
        if object_ansible_id:
            try:
                # Find the Resource object by its ansible_id
                resource_obj = Resource.objects.get(ansible_id=object_ansible_id)

                # Filter the queryset based on the resource's content_type and object_id
                queryset = queryset.filter(
                    object_role__content_type=resource_obj.content_type,
                    object_role__object_id=str(resource_obj.object_id) # Ensure object_id is string
                )
            except (Resource.DoesNotExist, ObjectDoesNotExist):
                # If the resource is not found or ansible_id is invalid, return an empty queryset
                return queryset.none()
            except ValueError:
                # Handle potential ValueError if ansible_id is not a valid UUID
                return queryset.none()

        return queryset

class UserAnsibleIdAliasFilterBackend(AnsibleIdAliasFilterBackend):
    """
    Filter backend for user ansible_id.

    Example:
    /api/v1/role_user_assignments/?user_ansible_id=80c7e291-b121-48fc-8fb1-174aac6f57a6
    """
    def filter_queryset(self, request, queryset, view):
        user_ansible_id = request.query_params.get('user_ansible_id')
        if user_ansible_id:
            queryset = queryset.filter(user__resource__ansible_id=user_ansible_id)
        return super().filter_queryset(request, queryset, view)

class TeamAnsibleIdAliasFilterBackend(AnsibleIdAliasFilterBackend):
    """
    Filter backend for team ansible_id.

    Example:
    /api/v1/role_team_assignments/?team_ansible_id=c2b59b42-a874-43ca-9e1f-abe410864f65
    """
    def filter_queryset(self, request, queryset, view):
        team_ansible_id = request.query_params.get('team_ansible_id')
        if team_ansible_id:
            queryset = queryset.filter(team__resource__ansible_id=team_ansible_id)
        return super().filter_queryset(request, queryset, view)
