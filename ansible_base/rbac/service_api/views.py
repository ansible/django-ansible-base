from crum import impersonate
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.lib.utils.schema import extend_schema_if_available
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import try_add_oauth2_scope_permission
from ansible_base.resource_registry.views import HasResourceRegistryPermissions
from ansible_base.rest_filters.rest_framework import ansible_id_backend
from ansible_base.rest_filters.rest_framework.ansible_id_backend import (
    ServiceFilterBackend,
)

from ..models import (
    DABContentType,
    DABPermission,
    RoleTeamAssignment,
    RoleUserAssignment,
)
from ..pipeline import bulk_give_permissions, remove_assignments
from ..policies import check_can_remove_assignment, check_content_obj_permission
from ..remote import RemoteObject
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


prefetch_related = ('created_by__resource', 'content_type', 'role_definition', 'content_object', 'object_role')


class BaseSerivceRoleAssignmentViewSet(
    AnsibleBaseDjangoAppApiView,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """List of assignments for cross-service communication"""

    batch_lookup_chunk_size = 100
    permission_classes = try_add_oauth2_scope_permission(
        [
            HasResourceRegistryPermissions,
        ]
    )
    assignment_actor_field = None
    batch_serializer_class = None
    # Handled by ServiceFilterBackend which adds OR-with-NULL for global assignments
    rest_filters_reserved_names = ('content_type__service', 'resource__ansible_id')

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

        # check permissions before removing a role assignment. Previously it was possible
        # to remove a role assignment for a remote object in Gateway with neither side (Gateway
        # and the remote side, e.g. Controller) checking if this was allowed.
        check_can_remove_assignment(request.user, existing)

        # Save properties for sync after it is done locally (at which point assignment will not exist)
        role_definition = existing.role_definition
        actor = existing.actor
        content_object = existing.content_object

        # Use standard DRF delete logic
        self.perform_destroy(existing)
        self.remote_secondary_sync_unassignment(role_definition, actor, content_object, from_service=serializer.validated_data.get('from_service'))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _validate_batch(self, request):
        batch_serializer = self.batch_serializer_class(data=request.data, context=self.get_serializer_context())
        batch_serializer.is_valid(raise_exception=True)

        source = str(batch_serializer.validated_data['from_service'])
        creator = batch_serializer.validated_data.get('created_by')
        assignment_data = batch_serializer.validated_data['assignments']
        for item in assignment_data:
            item['from_service'] = source
            item.pop('created_by', None)
            if creator is not None:
                item['created_by'] = creator
        return source, creator, assignment_data

    @staticmethod
    def _get_content_object(role_definition, validated_data):
        if role_definition.content_type_id is None:
            return None

        object_id = validated_data.get('object_id')
        if object_id in (None, ''):
            raise serializers.ValidationError({'object_id': 'Object must be specified for this role assignment'})

        model = role_definition.content_type.model_class()
        parent_reference = validated_data.get('parent_reference') or None
        try:
            if issubclass(model, RemoteObject):
                return model(content_type=role_definition.content_type, object_id=object_id, parent_reference=parent_reference)

            try:
                return model.objects.get(pk=object_id)
            except model.DoesNotExist:
                return RemoteObject(content_type=role_definition.content_type, object_id=object_id, parent_reference=parent_reference)
        except (ValueError, TypeError, DjangoValidationError) as exc:
            raise serializers.ValidationError({'object_id': 'Invalid primary key for this object type.'}) from exc

    def _get_permission_triples(self, assignment_data, request_user, check_object_permission=True):
        triples = []
        for item in assignment_data:
            role_definition = item['role_definition']
            actor = item[self.assignment_actor_field]
            content_object = self._get_content_object(role_definition, item)
            if check_object_permission and content_object is not None:
                check_content_obj_permission(request_user, content_object)
            triples.append((role_definition, actor, content_object))
        return triples

    def _assignment_key(self, role_definition, actor, content_object):
        if content_object is None:
            return role_definition.pk, actor.pk, None, None
        if isinstance(content_object, RemoteObject):
            content_type_id = content_object.content_type.pk
            object_id = str(content_object.object_id)
        else:
            content_type_id = role_definition.content_type_id
            object_id = str(content_object.pk)
        return role_definition.pk, actor.pk, content_type_id, object_id

    def _assignment_key_from_instance(self, assignment):
        return (
            assignment.role_definition_id,
            getattr(assignment, f'{self.assignment_actor_field}_id'),
            assignment.content_type_id,
            str(assignment.object_id) if assignment.object_id is not None else None,
        )

    def _find_existing_batch_assignments(self, triples, for_update=False):
        assignments = []
        for offset in range(0, len(triples), self.batch_lookup_chunk_size):
            query = Q()
            for role_definition, actor, content_object in triples[offset : offset + self.batch_lookup_chunk_size]:
                _role_id, _actor_id, content_type_id, object_id = self._assignment_key(role_definition, actor, content_object)
                query |= Q(
                    role_definition_id=role_definition.pk,
                    **{f'{self.assignment_actor_field}_id': actor.pk},
                    content_type_id=content_type_id,
                    object_id=object_id,
                )
            queryset = self.get_queryset().filter(query)
            if for_update:
                lock_kwargs = {'of': ('self',)} if connection.features.has_select_for_update_of else {}
                queryset = queryset.select_for_update(**lock_kwargs).order_by('pk')
            assignments.extend(queryset)
        return assignments

    def _get_new_batch_triples(self, triples):
        existing = self._find_existing_batch_assignments(triples)
        existing_keys = {self._assignment_key_from_instance(assignment) for assignment in existing}
        return [triple for triple in triples if self._assignment_key(*triple) not in existing_keys]

    def _get_unique_batch_triples(self, assignment_data, request_user):
        triples_by_key = {}
        for triple in self._get_permission_triples(assignment_data, request_user):
            triples_by_key.setdefault(self._assignment_key(*triple), triple)
        return list(triples_by_key.values())

    def _bulk_give_object_assignments(self, triples):
        if self.assignment_actor_field == 'user':
            return bulk_give_permissions(user_permissions=triples, ignore_conflicts=False)
        return bulk_give_permissions(team_permissions=triples, ignore_conflicts=False)

    def _create_object_batch_assignments(self, pending_triples):
        for _ in range(5):
            if not pending_triples:
                return []
            try:
                with transaction.atomic():
                    return self._bulk_give_object_assignments(pending_triples)
            except IntegrityError:
                # Strict inserts distinguish our writes from a concurrent request
                # that won the unique-assignment race. Retry only assignments still absent.
                pending_triples = self._get_new_batch_triples(pending_triples)

        if pending_triples:
            raise IntegrityError('Role assignment batch could not recover from concurrent inserts')
        return []

    def _give_global_batch_assignments(self, global_triples):
        assignments = []
        for role_definition, actor, _content_object in global_triples:
            assignment, created = role_definition.give_global_permission(actor, return_created=True)
            if created and assignment is not None:
                assignments.append(assignment)
        return assignments

    def _bulk_assign(self, request):
        source, creator, assignment_data = self._validate_batch(request)
        triples = self._get_unique_batch_triples(assignment_data, request.user)

        assignments = []
        with transaction.atomic():
            new_triples = self._get_new_batch_triples(triples)
            pending_object_triples = [triple for triple in new_triples if triple[2] is not None]
            global_triples = [triple for triple in new_triples if triple[2] is None]

            with impersonate(creator):
                assignments = self._create_object_batch_assignments(pending_object_triples)
                assignments.extend(self._give_global_batch_assignments(global_triples))

        for assignment in assignments:
            self.remote_secondary_sync_assignment(assignment, from_service=source)

        return Response({'created': len(assignments), 'existing': len(triples) - len(assignments)}, status=status.HTTP_200_OK)

    def _bulk_unassign(self, request):
        source, _creator, assignment_data = self._validate_batch(request)
        triples_by_key = {}
        for triple in self._get_permission_triples(assignment_data, request.user, check_object_permission=False):
            triples_by_key.setdefault(self._assignment_key(*triple), triple)
        triples = sorted(
            triples_by_key.values(),
            key=lambda triple: tuple('' if part is None else str(part) for part in self._assignment_key(*triple)),
        )

        with transaction.atomic():
            existing = self._find_existing_batch_assignments(triples, for_update=True)
            for assignment in existing:
                check_can_remove_assignment(request.user, assignment)

            object_assignments = [assignment for assignment in existing if assignment.object_role_id is not None]
            global_assignments = [assignment for assignment in existing if assignment.object_role_id is None]
            user_assignments = object_assignments if self.assignment_actor_field == 'user' else []
            team_assignments = object_assignments if self.assignment_actor_field == 'team' else []

            remove_assignments(user_assignments=user_assignments, team_assignments=team_assignments)
            for assignment in global_assignments:
                assignment.role_definition.remove_global_permission(assignment.actor)

        for assignment in existing:
            self.remote_secondary_sync_unassignment(
                assignment.role_definition,
                assignment.actor,
                assignment.content_object,
                from_service=source,
            )

        deleted_count = len(existing)
        return Response({'deleted': deleted_count, 'missing': len(triples) - deleted_count}, status=status.HTTP_200_OK)

    def perform_destroy(self, instance):
        if instance.content_type_id:
            with transaction.atomic():
                instance.role_definition.remove_permission(instance.actor, instance.content_object)
        else:
            with transaction.atomic():
                instance.role_definition.remove_global_permission(instance.actor)


class ServiceRoleUserAssignmentViewSet(BaseSerivceRoleAssignmentViewSet):
    """List of user assignments for cross-service communication"""

    resource_purpose = "RBAC role assignments for users on resources indexed from connected AAP services"

    serializer_class = service_serializers.ServiceRoleUserAssignmentSerializer
    batch_serializer_class = service_serializers.ServiceRoleUserAssignmentBatchSerializer
    assignment_actor_field = 'user'
    filter_backends = AnsibleBaseDjangoAppApiView.filter_backends + [
        ansible_id_backend.UserAnsibleIdAliasFilterBackend,
        ansible_id_backend.RoleAssignmentFilterBackend,
        ServiceFilterBackend,
    ]

    def get_queryset(self):
        return RoleUserAssignment.objects.select_related('object_role').prefetch_related('user__resource__content_type', *prefetch_related)

    @action(detail=False, methods=['post'], url_path='assign')
    def assign(self, request):
        return self._assign(request)

    @extend_schema_if_available(
        request=service_serializers.ServiceRoleUserAssignmentBatchSerializer,
        responses={status.HTTP_200_OK: service_serializers.BulkRoleAssignmentResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='bulk-assign')
    def bulk_assign(self, request):
        return self._bulk_assign(request)

    @action(detail=False, methods=['post'], url_path='unassign')
    def unassign(self, request):
        return self._unassign(request)

    @extend_schema_if_available(
        request=service_serializers.ServiceRoleUserAssignmentBatchSerializer,
        responses={status.HTTP_200_OK: service_serializers.BulkRoleUnassignmentResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='bulk-unassign')
    def bulk_unassign(self, request):
        return self._bulk_unassign(request)


class ServiceRoleTeamAssignmentViewSet(BaseSerivceRoleAssignmentViewSet):
    """List of team role assignments for cross-service communication"""

    resource_purpose = "RBAC role assignments for teams on resources indexed from connected AAP services"

    serializer_class = service_serializers.ServiceRoleTeamAssignmentSerializer
    batch_serializer_class = service_serializers.ServiceRoleTeamAssignmentBatchSerializer
    assignment_actor_field = 'team'
    filter_backends = AnsibleBaseDjangoAppApiView.filter_backends + [
        ansible_id_backend.TeamAnsibleIdAliasFilterBackend,
        ansible_id_backend.RoleAssignmentFilterBackend,
        ServiceFilterBackend,
    ]

    def get_queryset(self):
        return RoleTeamAssignment.objects.select_related('object_role').prefetch_related('team__resource__content_type', *prefetch_related)

    @action(detail=False, methods=['post'], url_path='assign')
    def assign(self, request):
        return self._assign(request)

    @action(detail=False, methods=['post'], url_path='unassign')
    def unassign(self, request):
        return self._unassign(request)

    @extend_schema_if_available(
        request=service_serializers.ServiceRoleTeamAssignmentBatchSerializer,
        responses={status.HTTP_200_OK: service_serializers.BulkRoleAssignmentResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='bulk-assign')
    def bulk_assign(self, request):
        return self._bulk_assign(request)

    @extend_schema_if_available(
        request=service_serializers.ServiceRoleTeamAssignmentBatchSerializer,
        responses={status.HTTP_200_OK: service_serializers.BulkRoleUnassignmentResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='bulk-unassign')
    def bulk_unassign(self, request):
        return self._bulk_unassign(request)


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
