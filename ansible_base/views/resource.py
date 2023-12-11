from django.db import transaction
from django.http import HttpResponseNotFound
from django.shortcuts import redirect
from django_filters import rest_framework as filters
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, mixins

from ansible_base.models import PostgresTransaction, Resource, ResourceType, get_registry, service_id
from ansible_base.serializers import DestroyResourceSerializer, ResourceSerializer, ResourceTypeSerializer, TransactionSerializer, get_resource_detail_view
from ansible_base.utils.transactions import commit_transaction, create_transaction, rollback_transaction


class ResourceFilter(filters.FilterSet):
    service_id = filters.CharFilter(field_name="_computed_service_id")
    ansible_id = filters.CharFilter(field_name="_ansible_id")
    resource_type = filters.CharFilter(field_name="content_type__resource_type__resource_type")

    class Meta:
        model = Resource
        fields = ["name", "object_id"]


class TransactionViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    queryset = PostgresTransaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAdminUser]
    lookup_field = "gid"

    @action(detail=True, methods=["post"])
    def commit(self, *args, **kwargs):
        gid = kwargs["gid"]
        commit_transaction(gid)

        return Response({"status": "commited"})

    @action(detail=True, methods=["post"])
    def rollback(self, *args, **kwargs):
        gid = kwargs["gid"]
        rollback_transaction(gid)

        return Response({"status": "rolled back"})

    @action(detail=False, methods=["post"])
    def flush_transactions(self, *args, **kwargs):
        rolled_back = []
        for psql_transaction in self.get_queryset():
            rollback_transaction(psql_transaction.gid)
            rolled_back.append(psql_transaction.gid)

        return Response({"rolled_back": rolled_back})


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
    filterset_class = ResourceFilter
    filter_backends = (filters.DjangoFilterBackend,)

    @action(detail=True, methods=['get'])
    def resource_detail(self, *args, **kwargs):
        obj = self.get_object()
        url = get_resource_detail_view(obj)

        if url:
            return redirect(url, permanent=False)

        return HttpResponseNotFound()

    def destroy(self, request, *args, **kwargs):
        data = DestroyResourceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        instance = self.get_object()

        if t_id := data.validated_data.get("transaction_id"):
            with transaction.atomic():
                self.perform_destroy(instance)
                create_transaction(t_id)
                return Response({"transaction": t_id, "vote_commit": True})

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
