from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend

from ansible_base.rbac.models import RoleDefinition


class RoleDefinitionScopeFilterBackend(BaseFilterBackend):
    """Filter role definitions by their assignable scope.

    Some consumers, such as the AuthenticatorMap role picker, can only use
    roles that do not require a specific target object. Without the parameter,
    all role definitions are returned for backward compatibility.

    Example: /api/v1/role_definitions/?assignable_scope=organization,team
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
