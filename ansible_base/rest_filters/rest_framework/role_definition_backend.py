from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend

from ansible_base.rbac.models import RoleDefinition


class RoleDefinitionScopeFilterBackend(BaseFilterBackend):
    """
    Filter backend for narrowing role_definition list results to roles usable
    without a specific target object (system, organization, or team scoped).

    Some consumers, like the picker for AuthenticatorMap's map_type='role',
    can only use roles in these scopes; resource-scoped roles (e.g. a role
    tied to a JobTemplate) need a target object those consumers can't supply.

    Without the parameter, all role definitions are returned (backward
    compatible).

    Example:
    /api/v1/role_definitions/?assignable_scope=organization,team
    """

    def filter_queryset(self, request, queryset, view):
        raw_scopes = request.query_params.get('assignable_scope')
        if not raw_scopes:
            return queryset

        scopes = [scope.strip() for scope in raw_scopes.split(',') if scope.strip()]
        try:
            q = RoleDefinition.assignable_scope_q(scopes)
        except ValueError as exc:
            raise ValidationError({'assignable_scope': str(exc)})

        return queryset.filter(q)
