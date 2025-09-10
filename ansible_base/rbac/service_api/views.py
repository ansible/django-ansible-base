from django.db import transaction
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import try_add_oauth2_scope_permission
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

    def _object_delete(self, request):
        """Delete ALL role assignments for a specific object"""
        from django.contrib.contenttypes.models import ContentType
        from ..models import ObjectRole
        
        # Validate required fields
        data = request.data
        if 'resource_type' not in data or 'resource_pk' not in data:
            return Response(
                {'error': 'resource_type and resource_pk are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get content type for the resource
            app_label, model = data['resource_type'].split('.')
            content_type = ContentType.objects.get(app_label=app_label, model=model)
            
            # Delete ALL assignments for this object (bulk operation)
            with transaction.atomic():
                deleted_count = self.get_queryset().filter(
                    content_type=content_type,
                    object_id=data['resource_pk']
                ).delete()[0]
                
                # Also delete the ObjectRoles themselves
                ObjectRole.objects.filter(
                    content_type=content_type,
                    object_id=data['resource_pk']
                ).delete()
            
            return Response({
                'message': f'Deleted {deleted_count} role assignments for {data["resource_type"]} {data["resource_pk"]}',
                'deleted_count': deleted_count
            }, status=status.HTTP_200_OK)
            
        except ContentType.DoesNotExist:
            return Response(
                {'error': f'Content type not found: {data["resource_type"]}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to delete assignments: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def perform_destroy(self, instance):
        if instance.content_type_id:
            with transaction.atomic():
                instance.role_definition.remove_permission(instance.actor, instance.content_object)
        else:
            with transaction.atomic():
                instance.role_definition.remove_global_permission(instance.actor)


class ServiceRoleUserAssignmentViewSet(BaseSerivceRoleAssignmentViewSet):
    """List of user assignments for cross-service communication"""

    queryset = RoleUserAssignment.objects.prefetch_related('user__resource', *prefetch_related)
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

    @action(detail=False, methods=['post'], url_path='object_delete')
    def object_delete(self, request):
        return self._object_delete(request)


class ServiceRoleTeamAssignmentViewSet(BaseSerivceRoleAssignmentViewSet):
    """List of team role assignments for cross-service communication"""

    queryset = RoleTeamAssignment.objects.prefetch_related('team__resource', *prefetch_related)
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

    @action(detail=False, methods=['post'], url_path='object_delete')
    def object_delete(self, request):
        return self._object_delete(request)
