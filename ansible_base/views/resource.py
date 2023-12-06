from django.db import transaction
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.models import Resource, ResourceType, get_registry, service_id
from ansible_base.serializers import ResourceSerializer, ResourceTypeSerializer


class ResourceViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """
    Index of all the resources in the system.
    """

    queryset = Resource.objects.select_related("content_type__resource_type").prefetch_related("content_object").all()
    serializer_class = ResourceSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "ansible_id"


class ResourceTypeViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    queryset = ResourceType.objects.all()
    serializer_class = ResourceTypeSerializer
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def perform_destroy(self, instance):
        instance.content_object.delete()
        instance.delete()


# Use classes from config as mixin here?
class UserRolesViewSet:
    pass


class TeamRoleViewSet:
    pass


class RoleDefinitionsViewSet:
    pass


class PermissionsViewSet:
    pass


class AuthorizeUserView:
    pass


class ServiceMetadataView(APIView):
    def get(self, request, **kwargs):
        registry = get_registry()
        return Response({"service_id": service_id(), "service_type": registry.api_config.service_type})
