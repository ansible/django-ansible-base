from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.lib.utils.views import ViewWithHeaders
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.registry import get_registry
from ansible_base.resource_registry.serializers import ResourceListSerializer, ResourceSerializer, ResourceTypeSerializer, get_resource_detail_view


class ResourceViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
    ViewWithHeaders,
):
    """
    Index of all the resources in the system.
    """

    queryset = Resource.objects.select_related("content_type__resource_type").all()
    serializer_class = ResourceSerializer
    permission_classes = [permissions.IsAdminUser]
    lookup_field = "ansible_id"

    def get_serializer_class(self):
        if self.action == "list":
            return ResourceListSerializer

        return super().get_serializer_class()

    def get_object(self):
        resource_id = self.kwargs[self.lookup_field]

        if ":" in resource_id:
            resource_id = resource_id.split(":")[1]

        return get_object_or_404(self.queryset, resource_id=resource_id)

    @action(detail=True, methods=['get'])
    def resource_detail(self, *args, **kwargs):
        obj = self.get_object()
        url = get_resource_detail_view(obj)

        if url:
            return redirect(url, permanent=False)

        return HttpResponseNotFound()

    def perform_destroy(self, instance):
        instance.delete_resource()


class ResourceTypeViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
    ViewWithHeaders,
):
    queryset = ResourceType.objects.all()
    serializer_class = ResourceTypeSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "name"
    lookup_value_regex = "[^/]+"


class ServiceMetadataView(ViewWithHeaders):
    def get(self, request, **kwargs):
        registry = get_registry()
        return Response({"service_id": service_id(), "service_type": registry.api_config.service_type})
