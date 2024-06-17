from itertools import chain

from django.shortcuts import render
from django.urls.exceptions import NoReverseMatch
from django.urls.resolvers import URLPattern
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.oauth2_provider.views import DABOAuth2UserViewsetMixin
from ansible_base.rbac import permission_registry
from ansible_base.rbac.api.permissions import AnsibleBaseObjectPermissions, AnsibleBaseUserPermissions
from ansible_base.rbac.policies import visible_users
from test_app import models, serializers


class TestAppViewSet(ModelViewSet, AnsibleBaseView):
    permission_classes = [AnsibleBaseObjectPermissions]
    prefetch_related = ()
    select_related = ()

    def apply_optimizations(self, qs):
        if self.prefetch_related:
            qs = qs.prefetch_related(*self.prefetch_related)
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        return qs

    def filter_queryset(self, qs):
        cls = qs.model
        if permission_registry.is_registered(cls):
            qs = cls.access_qs(self.request.user, queryset=qs)

        qs = self.apply_optimizations(qs)

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


class UserViewSet(DABOAuth2UserViewsetMixin, TestAppViewSet):
    queryset = models.User.objects.all()
    permission_classes = [AnsibleBaseUserPermissions]
    serializer_class = serializers.UserSerializer
    prefetch_related = ('created_by', 'modified_by', 'resource', 'resource__content_type')

    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs)
        qs = self.apply_optimizations(qs)
        return super().filter_queryset(qs)

    @action(detail=False, methods=['get'])
    def me(self, request, pk=None):
        user = request.user
        serializer = self.get_serializer(user)
        return Response(serializer.data)


class EncryptionModelViewSet(TestAppViewSet):
    serializer_class = serializers.EncryptionModelSerializer
    queryset = models.EncryptionModel.objects.all()


class RelatedFieldsTestModelViewSet(TestAppViewSet):
    queryset = models.RelatedFieldsTestModel.objects.all()  # needed for automatic basename from router
    serializer_class = serializers.RelatedFieldsTestModelSerializer


class InventoryViewSet(TestAppViewSet):
    serializer_class = serializers.InventorySerializer
    queryset = models.Inventory.objects.all()


class NamespaceViewSet(TestAppViewSet):
    serializer_class = serializers.NamespaceSerializer
    queryset = models.Namespace.objects.all()


class CollectionImportViewSet(TestAppViewSet):
    serializer_class = serializers.CollectionImportSerializer
    queryset = models.CollectionImport.objects.all()


class ParentNameViewSet(TestAppViewSet):
    serializer_class = serializers.ParentNameSerializer
    queryset = models.ParentName.objects.all()


class PositionModelViewSet(TestAppViewSet):
    serializer_class = serializers.PositionModelSerializer
    queryset = models.PositionModel.objects.all()


class WeirdPermViewSet(TestAppViewSet):
    serializer_class = serializers.WeirdPermSerializer
    queryset = models.WeirdPerm.objects.all()


class InstanceGroupViewSet(TestAppViewSet):
    serializer_class = serializers.InstanceGroupSerializer
    queryset = models.InstanceGroup.objects.all()


class CowViewSet(TestAppViewSet):
    serializer_class = serializers.CowSerializer
    queryset = models.Cow.objects.all()
    rbac_action = None
    # Reserved names corresponds to
    # test_app/tests/rest_filters/rest_framework/test_field_lookup_backend.py::test_view_level_ignore_field
    rest_filters_reserved_names = ['cud']

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
    from ansible_base.activitystream.urls import router as activitystream_router
    from ansible_base.authentication.urls import router as auth_router
    from ansible_base.oauth2_provider.urls import router as oauth2_provider_router
    from ansible_base.rbac.api.router import router as rbac_router
    from ansible_base.resource_registry.urls import service_router
    from test_app.router import router as test_app_router

    list_endpoints = {}
    urls = [
        activitystream_router.urls,
        auth_router.urls,
        oauth2_provider_router.urls,
        rbac_router.urls,
        test_app_router.urls,
        service_router.urls,
    ]
    for url in chain(*urls):
        # only want "root" list views, for example:
        # want '^users/$' [name='user-list']
        # do not want '^users/(?P<pk>[^/.]+)/organizations/$' [name='user-organizations-list'],
        if '-list' in url.name and url.pattern._regex.count('/') == 1:
            list_endpoints[url.name.removesuffix('-list')] = reverse(url.name, request=request, format=format)

    from ansible_base.api_documentation.urls import api_version_urls as docs_urls
    from ansible_base.authentication.urls import api_version_urls as authentication_urls

    for url in docs_urls + authentication_urls[1:]:
        if isinstance(url, URLPattern):
            try:
                list_endpoints[url.name] = reverse(url.name, request=request, format=format)
            except NoReverseMatch:
                pass

    list_endpoints['service-index'] = reverse('service-index-root', request=request, format=format)
    list_endpoints['role-metadata'] = reverse('role-metadata', request=request, format=format)

    return Response(list_endpoints)


class MemberGuideViewSet(TestAppViewSet):
    serializer_class = serializers.MemberGuideSerializer


class MultipleFieldsViewSet(TestAppViewSet):
    serializer_class = serializers.MultipleFieldsModelSerializer


class PublicDataViewSet(TestAppViewSet):
    serializer_class = serializers.PublicDataSerializer
    queryset = models.PublicData.objects.all()


class AnimalViewSet(TestAppViewSet):
    serializer_class = serializers.AnimalSerializer
    queryset = models.Animal.objects.all()


class CityViewSet(TestAppViewSet):
    serializer_class = serializers.CitySerializer
    queryset = models.City.objects.all()


################################################
# FRONTEND
################################################


def index_view(request):
    context = {}
    return render(request, 'index.html', context)
