from collections import OrderedDict
from typing import Type

from django.db import transaction
from django.db.models import Model
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.rbac.api.permissions import RoleDefinitionPermissions
from ansible_base.rbac.api.serializers import (
    RoleDefinitionDetailSerializer,
    RoleDefinitionSerializer,
    RoleMetadataSerializer,
    RoleTeamAssignmentSerializer,
    RoleUserAssignmentSerializer,
)
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.policies import check_content_obj_permission
from ansible_base.rbac.validators import check_locally_managed, permissions_allowed_for_role, system_roles_enabled


def list_combine_values(data: dict[Type[Model], list[str]]) -> list[str]:
    "Utility method to merge everything in .values() into a single list"
    ret = []
    for this_list in data.values():
        ret += this_list
    return ret


class RoleMetadataView(AnsibleBaseDjangoAppApiView, GenericAPIView):
    """General data about models and permissions tracked by django-ansible-base RBAC

    Information from this endpoint should be static given a server version.
    This reflects model definitions, registrations with the permission registry,
    and enablement of RBAC features in settings.

    allowed_permissions: Valid permissions for a role of a given content_type
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RoleMetadataSerializer

    def get(self, request, format=None):
        data = OrderedDict()
        allowed_permissions = OrderedDict()

        all_models = sorted(permission_registry.all_registered_models, key=lambda cls: cls._meta.model_name)

        role_model_types = list(all_models)
        if system_roles_enabled():
            role_model_types += [None]
        for cls in role_model_types:
            if cls is None:
                cls_repr = 'system'
            else:
                cls_repr = f"{permission_registry.get_resource_prefix(cls)}.{cls._meta.model_name}"
            allowed_permissions[cls_repr] = []
            for codename in list_combine_values(permissions_allowed_for_role(cls)):
                perm = permission_registry.permission_qs.get(codename=codename)
                ct = permission_registry.content_type_model.objects.get_for_id(perm.content_type_id)
                perm_repr = f"{permission_registry.get_resource_prefix(ct.model_class())}.{codename}"
                allowed_permissions[cls_repr].append(perm_repr)

        data['allowed_permissions'] = allowed_permissions

        serializer = self.get_serializer(data)

        return Response(serializer.data)


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
    permission_classes = [RoleDefinitionPermissions]

    def get_serializer_class(self):
        if self.action == 'update':
            return RoleDefinitionDetailSerializer
        return super().get_serializer_class()

    def _error_if_managed(self, instance):
        if instance.managed is True:
            raise ValidationError(_('Role is managed by the system'))

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

    def perform_create(self, serializer):
        return super().perform_create(serializer)

    def perform_destroy(self, instance):
        obj = instance.content_object
        if obj:
            check_content_obj_permission(self.request.user, obj)
            check_locally_managed(instance.role_definition)
            with transaction.atomic():
                instance.role_definition.remove_permission(instance.actor, obj)
        else:
            for permission in instance.role_definition.permissions.all():
                if not has_super_permission(self.request.user, permission.codename):
                    raise PermissionDenied
            with transaction.atomic():
                instance.role_definition.remove_global_permission(instance.actor)


class RoleTeamAssignmentViewSet(BaseAssignmentViewSet):
    """
    Use this endpoint to give a team permission to a resource or an organization.
    The needed data is the team, the role definition, and the object id.
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
    The needed data is the user, the role definition, and the object id.
    The object must be of the type specified in the role definition.
    The type given in the role definition and the provided object_id are used
    to look up the resource.

    After creation, the assignment cannot be edited, but can be deleted to
    remove those permissions.
    """

    serializer_class = RoleUserAssignmentSerializer
    prefetch_related = ('user',)
