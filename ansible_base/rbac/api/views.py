from django.db import transaction
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.rbac.api.permissions import AuthenticatedReadAdminChange
from ansible_base.rbac.api.serializers import (
    RoleDefinitionDetailSeraizler,
    RoleDefinitionSerializer,
    RoleTeamAssignmentSerializer,
    RoleUserAssignmentSerializer,
)
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import RoleDefinition


class RoleDefinitionViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    """
    Role Definitions (roles) contain a list of permissions and can be used to
    assign those permissions to a user or team through the respective
    assignment endpoints.

    Custom roles can be created, modified, and deleted through this endpoint.
    System-managed roles are shown here, which cannot be edited or deleted,
    but can be assigned to users.
    """

    queryset = RoleDefinition.objects.prefetch_related('created_by', 'modified_by', 'content_type', 'permissions')
    serializer_class = RoleDefinitionSerializer
    permission_classes = [AuthenticatedReadAdminChange]

    def get_serializer_class(self):
        if self.action == 'update':
            return RoleDefinitionDetailSeraizler
        return super().get_serializer_class()

    def _error_if_managed(self, instance):
        if instance.managed is True:
            raise ValidationError('Role is managed by the system')

    def perform_update(self, serializer):
        self._error_if_managed(serializer.instance)
        return super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._error_if_managed(instance)
        return super().perform_destroy(instance)


assignment_prefetch_base = ('content_object', 'content_type', 'role_definition', 'created_by', 'object_role')


class BaseAssignmentViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    # PUT and PATCH are not allowed because these are immutable
    http_method_names = ['get', 'post', 'head', 'options', 'delete']
    prefetch_related = ()

    def get_queryset(self):
        model = self.serializer_class.Meta.model
        if has_super_permission(self.request.user, 'view'):
            return model.objects.all()
        return model.visible_items(self.request.user).prefetch_related(*self.prefetch_related, *assignment_prefetch_base)

    def perform_destroy(self, instance):
        if not self.request.user.has_obj_perm(instance, 'change'):
            raise PermissionDenied

        rd = instance.object_role.role_definition
        obj = instance.object_role.content_object
        with transaction.atomic():
            rd.remove_permission(instance.actor, obj)


class RoleTeamAssignmentViewSet(BaseAssignmentViewSet):
    """
    Use this endpoint to give a team permission to a resource or an organization.
    The needed data is the user, the role definition, and the object id.
    The object must be of the type specified in the role definition.
    The type given in the role definition and the provided object_id are used
    to look up the resource.

    After creation, the assignment cannot be edited, but can be deleted to
    remove those permissions.
    """

    serializer_class = RoleTeamAssignmentSerializer
    prefetch_related = ('team',)


class RoleUserAssignmentViewSet(BaseAssignmentViewSet):
    """
    Use this endpoint to give a user permission to a resource or an organization.
    The needed data is the team, the role definition, and the object id.
    The object must be of the type specified in the role definition.
    The type given in the role definition and the provided object_id are used
    to look up the resource.

    After creation, the assignment cannot be edited, but can be deleted to
    remove those permissions.
    """

    serializer_class = RoleUserAssignmentSerializer
    prefetch_related = ('user',)
