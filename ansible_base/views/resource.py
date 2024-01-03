from django.db import transaction
from django.http import HttpResponseNotFound
from django.shortcuts import redirect
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.models import Resource, ResourceType, get_registry, service_id
from ansible_base.serializers import ResourceSerializer, ResourceTypeSerializer, get_resource_detail_view


# class ResourceFilter(filters.FilterSet):
#     service_id = filters.CharFilter(field_name="_computed_service_id")
#     ansible_id = filters.CharFilter(field_name="_ansible_id")
#     resource_type = filters.CharFilter(field_name="content_type__resource_type__resource_type")

#     class Meta:
#         model = Resource
#         fields = ["name", "object_id"]


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
    permission_classes = [permissions.IsAdminUser]
    lookup_field = "_ansible_id"

    @action(detail=True, methods=['get'])
    def resource_detail(self, *args, **kwargs):
        obj = self.get_object()
        url = get_resource_detail_view(obj)

        if url:
            return redirect(url, permanent=False)

        return HttpResponseNotFound()

    @transaction.atomic
    def perform_destroy(self, instance):
        instance.content_object.delete()
        instance.delete()


class ResourceTypeViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    queryset = ResourceType.objects.all()
    serializer_class = ResourceTypeSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "resource_type"
    lookup_value_regex = "[^/]+"


class ServiceMetadataView(APIView):
    def get(self, request, **kwargs):
        registry = get_registry()
        return Response({"service_id": service_id(), "service_type": registry.api_config.service_type})
