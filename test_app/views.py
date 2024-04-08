from django.shortcuts import render
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.rbac import permission_registry
from ansible_base.rbac.api.permissions import AnsibleBaseObjectPermissions
from test_app import models, serializers


class TestAppViewSet(ModelViewSet, AnsibleBaseView):
    permission_classes = [AnsibleBaseObjectPermissions]
    prefetch_related = ()
    select_related = ()

    def filter_queryset(self, qs):
        cls = self.serializer_class.Meta.model
        if permission_registry.is_registered(cls):
            qs = cls.access_qs(self.request.user, queryset=qs)

        if self.prefetch_related:
            qs = qs.prefetch_related(*self.prefetch_related)
        if self.select_related:
            qs = qs.select_related(*self.select_related)

        return super().filter_queryset(qs)


class OrganizationViewSet(TestAppViewSet):
    serializer_class = serializers.OrganizationSerializer
    prefetch_related = ('created_by', 'modified_by', 'resource', 'resource__content_type')
    queryset = models.Organization.objects.all()


class TeamViewSet(TestAppViewSet):
    serializer_class = serializers.TeamSerializer
    queryset = models.Team.objects.all()
    prefetch_related = ('created_by', 'modified_by', 'organization')
    # for demonstration purposes, this uses a select_related for the resource relationship
    select_related = ('resource__content_type',)


class UserViewSet(ModelViewSet):
    permission_classes = [AnsibleBaseObjectPermissions]
    serializer_class = serializers.UserSerializer
    queryset = models.User.objects.all()
    prefetch_related = ('created_by', 'modified_by', 'resource', 'resource__content_type')


class EncryptionModelViewSet(TestAppViewSet):
    serializer_class = serializers.EncryptionModelSerializer
    queryset = models.EncryptionModel.objects.all()


class RelatedFieldsTestModelViewSet(TestAppViewSet):
    queryset = models.RelatedFieldsTestModel.objects.all()  # needed for automatic basename from router
    serializer_class = serializers.RelatedFieldsTestModelSerializer


class InventoryViewSet(TestAppViewSet):
    serializer_class = serializers.InventorySerializer
    queryset = models.Inventory.objects.all()


class InstanceGroupViewSet(TestAppViewSet):
    serializer_class = serializers.InstanceGroupSerializer
    queryset = models.InstanceGroup.objects.all()


class CowViewSet(TestAppViewSet):
    serializer_class = serializers.CowSerializer
    queryset = models.Cow.objects.all()
    rbac_action = None

    @action(detail=True, rbac_action='say', methods=['post'])
    def cowsay(self, request, pk=None):
        self.get_object()  # this triggers the permission check
        return Response({'detail': 'moooooo'})


class UUIDModelViewSet(TestAppViewSet):
    serializer_class = serializers.UUIDModelSerializer
    queryset = models.UUIDModel.objects.all()


# create api root view from the router
@api_view(['GET'])
def api_root(request, format=None):
    from ansible_base.authentication.urls import router as auth_router
    from ansible_base.resource_registry.urls import service_router
    from ansible_base.activitystream.urls import router as activitystream_router
    from test_app.router import router

    list_endpoints = {}
    for url in router.urls + auth_router.urls + service_router.urls + activitystream_router.urls:
        # only want "root" list views, for example:
        # want '^users/$' [name='user-list']
        # do not want '^users/(?P<pk>[^/.]+)/organizations/$' [name='user-organizations-list'],
        if '-list' in url.name and url.pattern._regex.count('/') == 1:
            list_endpoints[url.name.removesuffix('-list')] = reverse(url.name, request=request, format=format)
    return Response(list_endpoints)


class MultipleFieldsViewSet(TestAppViewSet):
    serializer_class = serializers.MultipleFieldsModelSerializer


class AnimalViewSet(TestAppViewSet):
    serializer_class = serializers.AnimalSerializer


################################################
# FRONTEND
################################################


def index_view(request):
    context = {}
    return render(request, 'index.html', context)
