from collections import OrderedDict

from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.lib.utils.response import CSVStreamResponse
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.models.resource import resource_type_cache
from ansible_base.resource_registry.registry import get_registry
from ansible_base.resource_registry.serializers import ResourceListSerializer, ResourceSerializer, ResourceTypeSerializer, UserAuthenticationSerializer
from ansible_base.rest_filters.rest_framework.field_lookup_backend import FieldLookupBackend
from ansible_base.rest_filters.rest_framework.order_backend import OrderByBackend
from ansible_base.rest_filters.rest_framework.type_filter_backend import TypeFilterBackend


class HasResourceRegistryPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if user.is_superuser:
            return True

        if allowed_actions := getattr(user, "resource_api_actions", None):
            if allowed_actions == "*":
                return True
            else:
                return view.action in allowed_actions

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
    permission_classes = [
        HasResourceRegistryPermissions,
    ]
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

    @action(detail=True, methods=['get'])
    def additional_data(self, *args, **kwargs):
        obj = self.get_object()
        if serializer := resource_type_cache(obj.content_type.pk).serializer_class:
            data = serializer.get_additional_data(obj.content_object)
            if data is not None:
                return Response(data.data)

        return HttpResponseNotFound()

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
        yield ("ansible_id", "resource_hash", "modified")
        for resource in resources_qs:
            yield (resource.ansible_id, serializer_class(resource.content_object).get_hash(), resource.modified)

    @action(detail=True, methods=["get"])
    def manifest(self, request, name, *args, **kwargs):
        """
        Returns the as a stream the csv of resource_id,hash for a given resource type.
        """
        resource_type = get_object_or_404(ResourceType, name=name)
        if not resource_type.serializer_class:  # pragma: no cover
            return HttpResponseNotFound()

        resources = Resource.objects.filter(content_type__resource_type=resource_type).prefetch_related("content_object")
        if not resources:
            return HttpResponseNotFound()

        return CSVStreamResponse(self.serialize_resources_hashes(resources, resource_type.serializer_class)).stream()


class ServiceMetadataView(
    AnsibleBaseDjangoAppApiView,
):
    permission_classes = [
        HasResourceRegistryPermissions,
    ]

    def get(self, request, **kwargs):
        registry = get_registry()
        return Response({"service_id": service_id(), "service_type": registry.api_config.service_type})


class ServiceIndexRootView(AnsibleBaseDjangoAppApiView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, format=None):
        '''Link other resource registry endpoints'''

        data = OrderedDict()
        data['metadata'] = reverse('service-metadata')
        data['resources'] = reverse('resource-list')
        data['resource-types'] = reverse('resourcetype-list')
        return Response(data)


class ValidateLocalUserView(AnsibleBaseDjangoAppApiView):
    """
    Validate a user's username and password.
    """

    permission_classes = [
        HasResourceRegistryPermissions,
    ]

    def post(self, request, **kwargs):
        serializer = UserAuthenticationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        api_config = get_registry().api_config
        user = api_config.authenticate_local_user(serializer.validated_data["username"], serializer.validated_data["password"])

        if not user:
            return Response(status=401)

        return Response(data={"ansible_id": Resource.get_resource_for_object(user).ansible_id})
