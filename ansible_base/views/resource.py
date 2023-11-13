from rest_framework import permissions
from rest_framework.viewsets import mixins, GenericViewSet
from rest_framework.decorators import action
from rest_framework.response import Response

from ansible_base.models import Resource, Permission, ResourceType
from ansible_base.serializers import ResourceSerializer, ResourcePermissionSerializer, ResourceTypeSerializer


class ResourceViewSet(
    # mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """
    Index of all the resources in the system.
    """

    queryset = Resource.objects.all()
    serializer_class = ResourceSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "ansible_id"

    def get_serializer_for_resource(self, obj):
        return obj.content_type.resource_type.get_resource_config()["managed_serializer"]

    def get_object(self):
        resource = super().get_object()
        resource_serializer = self.get_serializer_for_resource(resource)
        if resource_serializer:
            return resource.content_object
        return resource

    def get_serializer_class(self):
        if not self.request or self.action != "retrieve":
            return self.serializer_class
        resource = super().get_object()
        resource_serializer = self.get_serializer_for_resource(resource)
        if resource_serializer:
            return resource_serializer
        return self.serializer_class

    @action(methods=["GET"], detail=True, serializer_class=ResourcePermissionSerializer)
    def permissions(self, request, ansible_id):
        obj = super().get_object()
        serializer = ResourcePermissionSerializer(Permission.objects.filter(resource_type=obj.content_type.resource_type), many=True)

        return Response(serializer.data)


class ResourceTypeViewSet(
    # mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    # mixins.UpdateModelMixin,
    # mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    queryset = ResourceType.objects.all()
    serializer_class = ResourceTypeSerializer
    permission_classes = [permissions.IsAuthenticated]
