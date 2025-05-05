import logging
from collections import OrderedDict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.lib.utils.response import CSVStreamResponse, get_relative_url
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import try_add_oauth2_scope_permission
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.registry import get_registry
from ansible_base.resource_registry.serializers import ResourceListSerializer, ResourceSerializer, ResourceTypeSerializer, UserAuthenticationSerializer
from ansible_base.resource_registry.utils.auth_code import get_user_auth_code
from ansible_base.rest_filters.rest_framework.field_lookup_backend import FieldLookupBackend
from ansible_base.rest_filters.rest_framework.order_backend import OrderByBackend
from ansible_base.rest_filters.rest_framework.type_filter_backend import TypeFilterBackend

logger = logging.getLogger('ansible_base.resource_registry.views')


class HasResourceRegistryPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if user.is_superuser:
            return True

        if allowed_actions := getattr(user, "resource_api_actions", None):
            if allowed_actions == "*":
                return True
            else:
                if hasattr(view, 'action'):
                    return view.action in allowed_actions
                elif hasattr(view, 'custom_action_label'):
                    return view.custom_action_label in allowed_actions
                else:
                    logger.warning(f'View {view} denied request because view action can not be identified')

        return False


class ResourcesPagination(PageNumberPagination):
    # PageNumberPagination by itself doesn't work in some apps because when api_settings.PAGE_SIZE
    # isn't set, the default is no pagination.
    page_size = 50


class ResourceAPIMixin:
    """
    The resource API is not intended to be consistent with the REST API on the service
    that it is hosted on. It is only intended to be consistent with itself. The point
    of the resource API is to provide the exact same interface on every single AAP service.
    To that end, we are not using any of the default DRF configurations for these views,
    rather we overriding all of them in order to provide the same experience everywhere.
    Regardless of where the ResourceAPI is served from it must:

    - Use DAB filters
    - Validate user access based on the AAP JWT token
    - Use Page/Number pagination
    """

    filter_backends = (FieldLookupBackend, TypeFilterBackend, OrderByBackend)
    permission_classes = try_add_oauth2_scope_permission(
        [
            HasResourceRegistryPermissions,
        ]
    )
    pagination_class = ResourcesPagination


class ResourceViewSet(
    ResourceAPIMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
    AnsibleBaseDjangoAppApiView,
):
    """
    Index of all the resources in the system.
    """

    queryset = Resource.objects.select_related("content_type__resource_type").all()
    serializer_class = ResourceSerializer
    lookup_field = "ansible_id"

    def get_serializer_class(self):
        if self.action == "list":
            return ResourceListSerializer

        return super().get_serializer_class()

    def perform_destroy(self, instance):
        instance.delete_resource()


class ResourceTypeViewSet(
    ResourceAPIMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
    AnsibleBaseDjangoAppApiView,
):
    """
    Index of the resource types that are configured in the system.
    """

    queryset = ResourceType.objects.all()
    serializer_class = ResourceTypeSerializer
    lookup_field = "name"
    lookup_value_regex = "[^/]+"

    def serialize_resources_hashes(self, resources_qs, serializer_class):
        """A generator that yields str sequences for csv stream response"""
        yield ("ansible_id", "resource_hash")
        for resource in resources_qs:
            yield (resource.ansible_id, serializer_class(resource.content_object).get_hash())

    @action(detail=True, methods=["get"])
    def manifest(self, request, name, *args, **kwargs):
        """
        Returns the as a stream the csv of resource_id,hash for a given resource type.
        """
        resource_type = get_object_or_404(ResourceType, name=name)
        if not resource_type.serializer_class:  # pragma: no cover
            return HttpResponseNotFound()

        if 'service_id' in request.query_params:
            if request.query_params['service_id'] == 'all':
                service_filter = Q()
            else:
                # Return this services resources plus the resources from the service requested
                service_filter = Q(service_id=service_id()) | Q(service_id=request.query_params['service_id'])
        else:
            service_filter = Q(service_id=service_id())

        resources = Resource.objects.filter(content_type__resource_type=resource_type).filter(service_filter).prefetch_related("content_object")

        if name == "shared.user" and (system_user := getattr(settings, "SYSTEM_USERNAME", None)):
            resources = resources.exclude(name=system_user)

        if not resources:
            return HttpResponseNotFound()

        return CSVStreamResponse(self.serialize_resources_hashes(resources, resource_type.serializer_class)).stream()


class ServiceMetadataView(
    AnsibleBaseDjangoAppApiView,
):
    permission_classes = try_add_oauth2_scope_permission(
        [
            HasResourceRegistryPermissions,
        ]
    )

    # Corresponds to viewset action but given a different name so schema generators are not messed up
    custom_action_label = "service-metadata"

    def get(self, request, **kwargs):
        registry = get_registry()
        return Response({"service_id": service_id(), "service_type": registry.api_config.service_type})


class ServiceIndexRootView(AnsibleBaseDjangoAppApiView):
    permission_classes = try_add_oauth2_scope_permission([permissions.IsAuthenticated])

    def get(self, request, format=None):
        '''Link other resource registry endpoints'''

        data = OrderedDict()
        data['metadata'] = get_relative_url('service-metadata')
        data['resources'] = get_relative_url('resource-list')
        data['resource-types'] = get_relative_url('resourcetype-list')
        return Response(data)


class ValidateLocalUserView(AnsibleBaseDjangoAppApiView):
    """
    Validate a user's username and password.
    """

    custom_action_label = "validate-local-user"

    permission_classes = [AllowAny]

    def post(self, request, **kwargs):
        serializer = UserAuthenticationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Ensure the users exists before authenticating
        PREFIX = getattr(settings, "RENAMED_USERNAME_PREFIX", "")
        viable_usernames = [serializer.validated_data["username"], PREFIX + serializer.validated_data["username"]]
        if not get_user_model().objects.filter(username__in=viable_usernames).exists():
            logger.debug(f"User {serializer.validated_data['username']} does not exist, not validating authentication")
            return Response(status=401)

        api_config = get_registry().api_config
        user = api_config.authenticate_local_user(serializer.validated_data["username"], serializer.validated_data["password"])

        if not user:
            return Response(status=401)

        try:
            auth_code = get_user_auth_code(user)
        except AttributeError:
            logger.exception(f"Cannot generate auth code for user {user}")
            auth_code = None

        response = {
            "ansible_id": Resource.get_resource_for_object(user).ansible_id,
            "auth_code": auth_code,
        }

        return Response(data=response)
