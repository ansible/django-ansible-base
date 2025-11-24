import uuid
from collections import OrderedDict
from typing import Type

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Model
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet, mixins

from ansible_base.lib.utils.auth import get_team_model, get_user_model
from ansible_base.lib.utils.schema import extend_schema_if_available
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import try_add_oauth2_scope_permission
from ansible_base.rbac.api.permissions import RoleDefinitionPermissions
from ansible_base.rbac.api.serializers import (
    RoleDefinitionDetailSerializer,
    RoleDefinitionSerializer,
    RoleMetadataSerializer,
    RoleTeamAssignmentSerializer,
    RoleUserAssignmentSerializer,
    TeamAccessAssignmentSerializer,
    TeamAccessListMixin,
    UserAccessAssignmentSerializer,
    UserAccessListMixin,
)
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.policies import check_can_remove_assignment
from ansible_base.rbac.validators import check_locally_managed, permissions_allowed_for_role, system_roles_enabled
from ansible_base.rest_filters.rest_framework import ansible_id_backend

from ..models import DABContentType, DABPermission, get_evaluation_model
from ..policies import check_content_obj_permission
from ..remote import RemoteObject, get_resource_prefix
from ..sync import maybe_reverse_sync_assignment, maybe_reverse_sync_role_definition, maybe_reverse_sync_unassignment
from .queries import assignment_qs_user_to_obj, assignment_qs_user_to_obj_perm


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

    permission_classes = try_add_oauth2_scope_permission([permissions.IsAuthenticated])
    serializer_class = RoleMetadataSerializer

    def __init__(self, *args, **kwargs):
        self.permission_cache = {}

    def dispatch(self, request, *args, **kwargs):
        # Warm cache to avoid hits to basically all types from serializer
        DABContentType.objects.get_for_models(*permission_registry.all_registered_models)
        return super().dispatch(request, *args, **kwargs)

    def get_for_codename(self, codename):
        if codename not in self.permission_cache:
            for permission in permission_registry.permission_qs.all():
                self.permission_cache[permission.codename] = permission
        return self.permission_cache[codename]

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
                cls_repr = f"{get_resource_prefix(cls)}.{cls._meta.model_name}"
            allowed_permissions[cls_repr] = []
            for codename in list_combine_values(permissions_allowed_for_role(cls)):
                perm = self.get_for_codename(codename)
                ct = permission_registry.content_type_model.objects.get_for_id(perm.content_type_id)
                perm_repr = f"{get_resource_prefix(ct.model_class())}.{codename}"
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

    resource_purpose = "RBAC roles defining permissions that can be managed and assigned to users and teams"

    queryset = RoleDefinition.objects.prefetch_related('created_by', 'modified_by', 'content_type', 'permissions', 'resource')
    serializer_class = RoleDefinitionSerializer
    permission_classes = try_add_oauth2_scope_permission([RoleDefinitionPermissions])

    def get_serializer_class(self):
        if self.action == 'update':
            return RoleDefinitionDetailSerializer
        return super().get_serializer_class()

    def _error_if_managed(self, instance):
        if instance.managed is True:
            raise ValidationError(_('Role is managed by the system'))

    def perform_create(self, serializer):
        from ansible_base.resource_registry.signals.handlers import no_reverse_sync

        with no_reverse_sync():
            super().perform_create(serializer)

        # Manually sync after permissions are fully saved
        maybe_reverse_sync_role_definition(serializer.instance, "create")

    def perform_update(self, serializer):
        from ansible_base.resource_registry.signals.handlers import no_reverse_sync

        self._error_if_managed(serializer.instance)

        with no_reverse_sync():
            super().perform_update(serializer)

        # Manually sync after permissions are fully saved
        serializer.instance.refresh_from_db()
        maybe_reverse_sync_role_definition(serializer.instance, "update")

    def perform_destroy(self, instance):
        self._error_if_managed(instance)
        return super().perform_destroy(instance)

    def dispatch(self, request, *args, **kwargs):
        # Warm cache to avoid hits to basically all types from serializer
        DABContentType.objects.get_for_models(*permission_registry.all_registered_models)
        return super().dispatch(request, *args, **kwargs)


assignment_prefetch_base = ('content_object', 'content_type', 'role_definition', 'created_by', 'object_role')


class BaseAssignmentViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    permission_classes = try_add_oauth2_scope_permission([permissions.IsAuthenticated])
    # PUT and PATCH are not allowed because these are immutable
    http_method_names = ['get', 'post', 'head', 'options', 'delete']
    prefetch_related = ()

    def get_queryset(self):
        model = self.serializer_class.Meta.model
        return model.objects.prefetch_related(*self.prefetch_related, *assignment_prefetch_base)

    def filter_queryset(self, qs):
        model = self.serializer_class.Meta.model
        if has_super_permission(self.request.user, 'view'):
            new_qs = qs
        else:
            new_qs = model.visible_items(self.request.user, qs)
        return super().filter_queryset(new_qs)

    def remote_sync_assignment(self, assignment):
        "Intermediary for sync method so that child classes can modify it purely in viewset"
        maybe_reverse_sync_assignment(assignment)

    def remote_sync_unassignment(self, role_definition, actor, content_object):
        maybe_reverse_sync_unassignment(role_definition, actor, content_object)

    def perform_create(self, serializer):
        ret = super().perform_create(serializer)
        self.remote_sync_assignment(serializer.instance)
        return ret

    def perform_destroy(self, instance):
        check_can_remove_assignment(self.request.user, instance)
        check_locally_managed(instance.role_definition)

        # Save properties for sync after it is done locally (at which point assignment will not exist)
        role_definition = instance.role_definition
        actor = instance.actor
        content_object = instance.content_object

        if instance.content_type_id:
            with transaction.atomic():
                instance.role_definition.remove_permission(instance.actor, instance.content_object)
        else:
            with transaction.atomic():
                instance.role_definition.remove_global_permission(instance.actor)

        self.remote_sync_unassignment(role_definition, actor, content_object)


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

    resource_purpose = "RBAC role grants assigning permissions to teams for specific resources"

    serializer_class = RoleTeamAssignmentSerializer
    prefetch_related = ('team__resource',)
    filter_backends = BaseAssignmentViewSet.filter_backends + [
        ansible_id_backend.TeamAnsibleIdAliasFilterBackend,
        ansible_id_backend.RoleAssignmentFilterBackend,
    ]


# Schema fragments for RoleUserAssignmentViewSet OpenAPI spec
# Note: These describe the valid patterns but cannot enforce mutual exclusivity in OpenAPI
# The actual validation is handled by the serializer's validate() method
_USER_ACTOR_REQUIREMENT = {
    'description': 'Must provide exactly one of: user (integer ID) or user_ansible_id (UUID). Mutual exclusivity enforced by server validation.',
    'properties': {
        'user': {'type': 'integer', 'nullable': True, 'description': 'ID of the user to assign the role to. Mutually exclusive with user_ansible_id.'},
        'user_ansible_id': {
            'type': 'string',
            'format': 'uuid',
            'nullable': True,
            'description': 'Ansible ID of the user to assign the role to. Mutually exclusive with user.',
        },
    },
}

_OBJECT_ID_REQUIREMENT = {
    'description': (
        'Can provide at most one of: object_id or object_ansible_id. '
        'Omit both for global role assignments. Mutual exclusivity enforced by server validation.'
    ),
    'properties': {
        'object_id': {
            'oneOf': [{'type': 'integer'}, {'type': 'string', 'format': 'uuid'}],
            'nullable': True,
            'description': 'ID of the resource object. Mutually exclusive with object_ansible_id.',
        },
        'object_ansible_id': {
            'type': 'string',
            'format': 'uuid',
            'nullable': True,
            'description': 'Ansible ID of the resource object. Mutually exclusive with object_id.',
        },
    },
}


class RoleUserAssignmentViewSet(BaseAssignmentViewSet):

    resource_purpose = "RBAC role grants assigning permissions to users for specific resources"

    serializer_class = RoleUserAssignmentSerializer
    prefetch_related = ('user__resource',)
    filter_backends = BaseAssignmentViewSet.filter_backends + [
        ansible_id_backend.UserAnsibleIdAliasFilterBackend,
        ansible_id_backend.RoleAssignmentFilterBackend,
    ]

    @extend_schema_if_available(
        request={
            'application/json': {
                'allOf': [
                    {'$ref': '#/components/schemas/RoleUserAssignment'},
                    _USER_ACTOR_REQUIREMENT,
                    _OBJECT_ID_REQUIREMENT,
                ]
            },
        },
        description="Give a user permission to a resource, an organization, or globally (when allowed). "
        "Must specify 'role_definition' and exactly one of 'user' or 'user_ansible_id'. "
        "Can specify at most one of 'object_id' or 'object_ansible_id' (omit both for global roles). "
        "The content_type of the role definition and the provided object_id are used to look up the resource. "
        "After creation, the assignment cannot be edited, but can be deleted to remove those permissions.",
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)


class AccessURLMixin:
    def get_actor_model(self):
        return get_user_model()

    def get_url_permission(self):
        model_name = self.kwargs.get("model_name")
        # Prefer treating the URL as requesting for some permission
        return DABPermission.objects.filter(api_slug=model_name).first()

    def get_url_content_type(self):
        if getattr(self, 'permission', None):
            # Access list will be all permissions for the given object
            return self.permission.content_type

        model_name = self.kwargs.get("model_name")
        content_type = DABContentType.objects.filter(api_slug=model_name).first()
        if not content_type:
            raise NotFound(f'The slug {model_name} is not a valid permission or type identifier')

        return content_type

    def get_url_obj(self):
        model_cls = self.content_type.model_class()
        object_id = self.kwargs.get("pk")
        if not issubclass(model_cls, RemoteObject):
            try:
                return model_cls.objects.get(pk=object_id)
            except model_cls.DoesNotExist:
                raise NotFound(f'The primary key {object_id} was not found for model {model_cls}')
        else:
            return model_cls(content_type=self.content_type, object_id=object_id)

    def check_permission_to_object(self, obj):
        try:
            if not self.request.user.has_obj_perm(obj, 'view'):
                raise NotFound
        except RuntimeError:
            check_content_obj_permission(self.request.user, obj)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()

        # To satisfy AWX schema generator
        if getattr(self, 'swagger_fake_view', False):
            return ctx

        self.get_data_from_url()

        ctx.update(
            {
                "permission": self.permission,
                "related_object": self.related_object,
                "content_type": self.content_type,
            }
        )
        return ctx


class UserAccessViewSet(
    AccessURLMixin,
    AnsibleBaseDjangoAppApiView,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """
    Use this endpoint to get a list of users who have access to a resource.
    This is a list-only view that provides a list of users, plus extra data.
    """

    serializer_mixin = UserAccessListMixin
    permission_classes = try_add_oauth2_scope_permission([permissions.IsAuthenticated])

    def get_data_from_url(self):
        if not hasattr(self, 'related_object'):
            self.permission = self.get_url_permission()
            self.content_type = self.get_url_content_type()
            self.related_object = self.get_url_obj()
            self.check_permission_to_object(self.related_object)
        return (self.permission, self.content_type, self.related_object)

    def get_queryset(self):
        actor_cls = self.get_actor_model()

        # To satisfy AWX schema generator
        if getattr(self, 'swagger_fake_view', False):
            return actor_cls.objects.none()

        permission, ct, obj = self.get_data_from_url()

        evaluation_cls = get_evaluation_model(obj)
        reverse_name = evaluation_cls._meta.get_field('role').remote_field.name
        assignment_cls = actor_cls._meta.get_field('role_assignments').related_model

        if permission:
            obj_eval_qs = evaluation_cls.objects.filter(codename=permission.codename, object_id=obj.pk, content_type_id=ct.id)
        else:
            # All relevant evaluations for the object
            obj_eval_qs = evaluation_cls.objects.filter(object_id=obj.pk, content_type_id=ct.id)
        obj_assignment_qs = assignment_cls.objects.filter(**{f'object_role__{reverse_name}__in': obj_eval_qs})

        if permission:
            global_assignment_qs = assignment_cls.objects.filter(content_type=None, role_definition__permissions=permission)
        else:
            global_assignment_qs = assignment_cls.objects.filter(content_type=None, role_definition__permissions__content_type=ct)

        assignment_qs = obj_assignment_qs | global_assignment_qs
        actor_qs = actor_cls.objects.filter(role_assignments__in=assignment_qs)
        if actor_cls._meta.model_name == 'user':
            actor_qs |= actor_cls.objects.filter(is_superuser=True)
        return actor_qs.distinct()

    def get_serializer(self, *args, **kwargs):
        """Awkwardly override this method, because eda-server uses a custom base viewset class.

        Due to how that is structured, you can not go without defining the model unless overwriting this.
        And we, here, can not give a serializer class at import time because the user model is unknown.
        So this is the same as the DRF method.
        """
        serializer_class = self.get_serializer_class()
        kwargs.setdefault('context', self.get_serializer_context())
        return serializer_class(*args, **kwargs)

    def get_serializer_class(self):
        actor_cls = self.get_actor_model()

        class DynamicActorSerializer(self.serializer_mixin):
            class Meta:
                model = actor_cls
                fields = self.serializer_mixin._expected_fields
                ref_name = f"{self.__class__.__name__}_{actor_cls.__name__}_Serializer"

        return DynamicActorSerializer


class TeamAccessViewSet(UserAccessViewSet):
    serializer_mixin = TeamAccessListMixin

    def get_actor_model(self):
        return get_team_model()


class UserAccessAssignmentViewSet(
    AccessURLMixin,
    AnsibleBaseDjangoAppApiView,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """
    This gives drill-down information about the means of inheritance
    for all the permissions show in the higher-level view of the access list
    """

    serializer_class = UserAccessAssignmentSerializer
    permission_classes = try_add_oauth2_scope_permission([permissions.IsAuthenticated])

    def get_url_actor(self):
        actor_pk = self.kwargs.get("actor_pk")
        actor_cls = self.get_actor_model()

        # First, try to parse as UUID for ansible_id lookup
        try:
            parsed_uuid = uuid.UUID(actor_pk)
            # It's a valid UUID, try resource lookup first
            try:
                resource_cls = apps.get_model('dab_resource_registry', 'Resource')
                resource = resource_cls.objects.get(ansible_id=parsed_uuid)
                actor = resource.content_object
                # Verify the content object is the correct type
                if isinstance(actor, actor_cls):
                    return actor
                else:
                    raise NotFound(f'Resource with ansible_id {parsed_uuid} is not a {actor_cls._meta.model_name}')
            except (LookupError, ObjectDoesNotExist):
                # Resource registry not available or resource not found with this UUID
                raise NotFound(f'The {actor_cls._meta.model_name} with ansible_id={actor_pk} can not be found')
        except ValueError:
            # Not a valid UUID, continue with primary key lookup
            pass

        # Fallback to primary key lookup (only for non-UUID values)
        try:
            return actor_cls.objects.get(pk=actor_pk)
        except actor_cls.DoesNotExist:
            raise NotFound(f'The {actor_cls._meta.model_name} with pk={actor_pk} can not be found')

    def get_data_from_url(self):
        if not hasattr(self, 'related_object'):
            self.permission = self.get_url_permission()
            self.content_type = self.get_url_content_type()
            self.related_object = self.get_url_obj()
            self.actor = self.get_url_actor()
            self.check_permission_to_object(self.related_object)
        return (self.permission, self.content_type, self.related_object, self.actor)

    def get_queryset(self):
        # To satisfy AWX schema generator
        if getattr(self, 'swagger_fake_view', False):
            return self.serializer_class.Meta.model.objects.none()

        permission, ct, obj, actor = self.get_data_from_url()

        if permission:
            return assignment_qs_user_to_obj_perm(actor, obj, permission)
        else:
            return assignment_qs_user_to_obj(actor, obj)


class TeamAccessAssignmentViewSet(UserAccessAssignmentViewSet):
    serializer_class = TeamAccessAssignmentSerializer

    def get_actor_model(self):
        return get_team_model()
