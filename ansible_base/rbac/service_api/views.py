from django.db import transaction
from django.db.models import OuterRef, Subquery
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.lib.utils.schema import extend_schema_if_available
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import try_add_oauth2_scope_permission
from ansible_base.resource_registry.models import Resource
from ansible_base.resource_registry.views import HasResourceRegistryPermissions
from ansible_base.rest_filters.rest_framework import ansible_id_backend

from ..models import DABContentType, DABPermission, RoleTeamAssignment, RoleUserAssignment
from . import serializers as service_serializers


class RoleContentTypeViewSet(
    AnsibleBaseDjangoAppApiView,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """List of types registered with the RBAC system, or loaded in from external system"""

    queryset = DABContentType.objects.prefetch_related('parent_content_type').all()
    serializer_class = service_serializers.DABContentTypeSerializer
    permission_classes = try_add_oauth2_scope_permission([permissions.IsAuthenticated])


class RolePermissionTypeViewSet(
    AnsibleBaseDjangoAppApiView,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """List of permissions managed with the RBAC system"""

    queryset = DABPermission.objects.prefetch_related('content_type').all()
    serializer_class = service_serializers.DABPermissionSerializer
    permission_classes = try_add_oauth2_scope_permission([permissions.IsAuthenticated])


# NOTE: role definitions are exchanged via the resources endpoint, so not included here


prefetch_related = ('created_by__resource', 'content_type', 'role_definition')


class BaseSerivceRoleAssignmentViewSet(
    AnsibleBaseDjangoAppApiView,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """List of assignments for cross-service communication"""

    permission_classes = try_add_oauth2_scope_permission(
        [
            HasResourceRegistryPermissions,
        ]
    )

    def remote_secondary_sync_assignment(self, assignment, from_service=None):
        """To allow service-specific sync when getting assignment from /service-index/ endpoint

        Will get a None value for from_service is the superuser is manually testing this endpoint.
        """
        pass

    def remote_secondary_sync_unassignment(self, role_definition, actor, content_object, from_service=None):
        "To allow service-specific sync when removing an assignment via this viewset"
        pass

    def _assign(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        existing = serializer.find_existing_assignment(self.get_queryset())
        if existing:
            output_serializer = self.get_serializer(existing)
            return Response(output_serializer.data, status=status.HTTP_200_OK)

        instance = serializer.save()
        self.remote_secondary_sync_assignment(serializer.instance, from_service=serializer.validated_data.get('from_service'))
        output_serializer = self.get_serializer(instance)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def _unassign(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        existing = serializer.find_existing_assignment(self.get_queryset())
        if not existing:
            output_serializer = self.get_serializer(existing)
            return Response(output_serializer.data, status=status.HTTP_200_OK)

        # Save properties for sync after it is done locally (at which point assignment will not exist)
        role_definition = existing.role_definition
        actor = existing.actor
        content_object = existing.content_object

        # Use standard DRF delete logic
        self.perform_destroy(existing)
        self.remote_secondary_sync_unassignment(role_definition, actor, content_object, from_service=serializer.validated_data.get('from_service'))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_destroy(self, instance):
        if instance.content_type_id:
            with transaction.atomic():
                instance.role_definition.remove_permission(instance.actor, instance.content_object)
        else:
            with transaction.atomic():
                instance.role_definition.remove_global_permission(instance.actor)


def resource_ansible_id_expr(ct_field='content_type_id', oid_field='object_id'):
    return Subquery(
        Resource.objects.filter(
            content_type_id=OuterRef(ct_field),
            object_id=OuterRef(oid_field),
        ).values(
            'ansible_id'
        )[:1]
    )


class ServiceRoleUserAssignmentViewSet(BaseSerivceRoleAssignmentViewSet):
    """List of user assignments for cross-service communication"""

    resource_purpose = "RBAC role assignments for users on resources indexed from connected AAP services"

    queryset = RoleUserAssignment.objects.prefetch_related('user__resource__content_type', *prefetch_related).annotate(
        _object_ansible_id_annotation=resource_ansible_id_expr()
    )
    serializer_class = service_serializers.ServiceRoleUserAssignmentSerializer
    filter_backends = AnsibleBaseDjangoAppApiView.filter_backends + [
        ansible_id_backend.UserAnsibleIdAliasFilterBackend,
        ansible_id_backend.RoleAssignmentFilterBackend,
    ]

    @action(detail=False, methods=['post'], url_path='assign')
    def assign(self, request):
        return self._assign(request)

    @action(detail=False, methods=['post'], url_path='unassign')
    def unassign(self, request):
        return self._unassign(request)


class ServiceRoleTeamAssignmentViewSet(BaseSerivceRoleAssignmentViewSet):
    """List of team role assignments for cross-service communication"""

    resource_purpose = "RBAC role assignments for teams on resources indexed from connected AAP services"

    queryset = RoleTeamAssignment.objects.prefetch_related('team__resource__content_type', *prefetch_related).annotate(
        _object_ansible_id_annotation=resource_ansible_id_expr()
    )
    serializer_class = service_serializers.ServiceRoleTeamAssignmentSerializer
    filter_backends = AnsibleBaseDjangoAppApiView.filter_backends + [
        ansible_id_backend.TeamAnsibleIdAliasFilterBackend,
        ansible_id_backend.RoleAssignmentFilterBackend,
    ]

    @action(detail=False, methods=['post'], url_path='assign')
    def assign(self, request):
        return self._assign(request)

    @action(detail=False, methods=['post'], url_path='unassign')
    def unassign(self, request):
        return self._unassign(request)


class ServiceObjectDeleteViewSet(viewsets.ViewSet):
    """
    Bulk deletion of role assignments for deleted objects.
    Uses standard create() method to bypass service token authentication restrictions.
    Handles both user and team assignments in a single API call.
    """

    permission_classes = try_add_oauth2_scope_permission([HasResourceRegistryPermissions])

    @extend_schema_if_available(extensions={'x-ai-description': 'Remove all role assignments for a resource indexed from connected AAP services'})
    def create(self, request):
        """
        Delete all role assignments (user and team) for a specific resource.

        Expected request data:
        {
            "resource_type": "main.inventory",
            "resource_pk": "4"
        }
        """
        from ..models import DABContentType

        # Validate request data
        serializer_data = {
            'resource_type': request.data.get('resource_type'),
            'resource_pk': request.data.get('resource_pk'),
        }

        if not serializer_data['resource_type'] or not serializer_data['resource_pk']:
            return Response({'error': 'Both resource_type and resource_pk are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Parse resource_type (e.g., "main.inventory" -> app_label="main", model="inventory")
            app_label, model_name = serializer_data['resource_type'].split('.', 1)
        except ValueError:
            return Response({'error': 'Invalid resource_type format. Expected: app_label.model_name'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Get the content type
            content_type = DABContentType.objects.get(app_label=app_label, model=model_name)
        except DABContentType.DoesNotExist:
            return Response({'error': f'Content type not found: {serializer_data["resource_type"]}'}, status=status.HTTP_400_BAD_REQUEST)

        # Perform bulk deletion in a transaction
        with transaction.atomic():
            # Delete user role assignments
            user_deleted_count = RoleUserAssignment.objects.filter(content_type=content_type, object_id=serializer_data['resource_pk']).delete()[0]

            # Delete team role assignments
            team_deleted_count = RoleTeamAssignment.objects.filter(content_type=content_type, object_id=serializer_data['resource_pk']).delete()[0]

        total_deleted = user_deleted_count + team_deleted_count

        return Response(
            {
                'message': f'Deleted {total_deleted} role assignments for {serializer_data["resource_type"]} {serializer_data["resource_pk"]}',
                'deleted_count': total_deleted,
                'breakdown': {'user_assignments_deleted': user_deleted_count, 'team_assignments_deleted': team_deleted_count},
            },
            status=status.HTTP_200_OK,
        )
