import logging
import time
from itertools import chain

import requests as req_lib
from django.http import JsonResponse
from django.shortcuts import render
from django.urls.exceptions import NoReverseMatch
from django.urls.resolvers import URLPattern
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.response import get_fully_qualified_url
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from ansible_base.oauth2_provider.views import DABOAuth2UserViewsetMixin
from ansible_base.rbac import permission_registry
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.policies import visible_users
from test_app import models, serializers

logger = logging.getLogger(__name__)


class TestAppViewSet(ModelViewSet, AnsibleBaseView):
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
    permission_classes = [OAuth2ScopePermission, AnsibleBaseUserPermissions]
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
            list_endpoints[url.name.removesuffix('-list')] = get_fully_qualified_url(url.name, request=request, format=format)

    from ansible_base.api_documentation.urls import api_version_urls as docs_urls
    from ansible_base.authentication.urls import api_version_urls as authentication_urls

    for url in docs_urls + authentication_urls[1:]:
        if isinstance(url, URLPattern):
            try:
                list_endpoints[url.name] = get_fully_qualified_url(url.name)
            except NoReverseMatch:
                pass

    list_endpoints['service-index'] = get_fully_qualified_url('service-index-root')
    list_endpoints['role-metadata'] = get_fully_qualified_url('role-metadata')
    list_endpoints['timeout-view'] = get_fully_qualified_url('test-timeout-view')
    list_endpoints['profile-stories'] = get_fully_qualified_url('profile-stories')

    return Response(list_endpoints)


@api_view(['GET'])
def timeout_view(request, format=None):
    time.sleep(60 * 10)  # 10 minutes


class MultipleFieldsViewSet(TestAppViewSet):
    serializer_class = serializers.MultipleFieldsModelSerializer


class PublicDataViewSet(TestAppViewSet):
    serializer_class = serializers.PublicDataSerializer
    queryset = models.PublicData.objects.all()


class AnimalViewSet(TestAppViewSet):
    serializer_class = serializers.AnimalSerializer
    queryset = models.Animal.objects.all()

    @action(detail=False, methods=['post'])
    def upload(self, request):
        return Response({'result': 'ok'})


class CityViewSet(TestAppViewSet):
    serializer_class = serializers.CitySerializer
    queryset = models.City.objects.all()


################################################
# Test ViewSets for api_documentation preprocessing hooks
################################################


class TestViewSetWithSkipAI(TestAppViewSet):
    """ViewSet for testing skip_ai_description attribute."""

    skip_ai_description = True
    serializer_class = serializers.TeamSerializer
    queryset = models.Team.objects.all()


class TestViewSetWithResourcePurpose(TestAppViewSet):
    """ViewSet for testing resource_purpose attribute."""

    resource_purpose = "test resources for validating purpose-based descriptions"
    serializer_class = serializers.TeamSerializer
    queryset = models.Team.objects.all()


class TestViewSetWithBothAttributes(TestAppViewSet):
    """ViewSet for testing both skip_ai_description and resource_purpose."""

    skip_ai_description = True
    resource_purpose = "test resources that should be skipped"
    serializer_class = serializers.TeamSerializer
    queryset = models.Team.objects.all()


################################################
# FRONTEND
################################################


def index_view(request):
    logger.info('index page loaded')
    context = {}
    return render(request, 'index.html', context)


def observability_headers_echo(request):
    headers = {k: v for k, v in request.META.items() if k.startswith('HTTP_')}
    return JsonResponse({"headers": headers})


def observability_headers_start(request):
    echo_url = request.build_absolute_uri('/api/v1/otel/observability-headers-echo/')
    response = req_lib.get(echo_url)
    return JsonResponse({"upstream_headers": response.json().get("headers", {})})


def otel_traces(_request):
    from test_app import otlp_server

    # Flush any buffered spans before reading
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'force_flush'):
        provider.force_flush(timeout_millis=2000)

    with otlp_server._lock:
        data = list(otlp_server.recent_spans)
    return JsonResponse({"traces": data})


def otel_logs(_request):
    from test_app import otlp_server

    provider = get_logger_provider()
    if hasattr(provider, 'force_flush'):
        provider.force_flush(timeout_millis=2000)

    with otlp_server._lock:
        data = list(otlp_server.recent_logs)
    return JsonResponse({"logs": data})


################################################
# PROFILE STORIES
################################################


@api_view(['GET'])
def profile_stories_root(request, format=None):
    return Response(
        {
            'org-delete': get_fully_qualified_url('profile-stories-org-delete', request=request),
        }
    )


@api_view(['GET'])
def org_delete_root(request, format=None):
    return Response(
        {
            'populate': get_fully_qualified_url('org-delete-populate', request=request),
            'bare': get_fully_qualified_url('org-delete-bare', request=request),
            'deferred': get_fully_qualified_url('org-delete-deferred', request=request),
            'optimized': get_fully_qualified_url('org-delete-optimized', request=request),
        }
    )


ORG_DELETE_PREFIX = 'scale-profile'


@api_view(['GET'])
def org_delete_populate(request, format=None):
    from django.contrib.auth import get_user_model

    from ansible_base.rbac.models import RoleDefinition

    # Uppercase is intentional -- follows Django convention for model classes (S117)
    User = get_user_model()  # noqa: N806
    n_teams = int(request.query_params.get('teams', 20))
    users_per_team = int(request.query_params.get('users', 2))
    org_name = f'{ORG_DELETE_PREFIX}-org'

    from ansible_base.activitystream import deferred_activity_stream
    from ansible_base.rbac.triggers import defer_rbac_computations

    if models.Organization.objects.filter(name=org_name).exists():
        with defer_rbac_computations():
            models.Organization.objects.filter(name=org_name).delete()

    org = models.Organization.objects.create(name=org_name)
    member_rd = RoleDefinition.objects.managed.team_member
    org_admin_rd = RoleDefinition.objects.managed.org_admin

    from ansible_base.rbac.models import DABPermission

    inv_ct = permission_registry.content_type_model.objects.get_for_model(models.Inventory)
    inv_admin_rd, created = RoleDefinition.objects.get_or_create(
        name=f'{ORG_DELETE_PREFIX}-inv-admin',
        defaults={'content_type': inv_ct, 'managed': False},
    )
    if created:
        inv_admin_rd.permissions.set(DABPermission.objects.filter(codename__in=['view_inventory', 'change_inventory', 'update_inventory']))

    total_users = 0
    all_users = []
    teams = []
    with deferred_activity_stream():
        # Resource creation deferred — RBAC recomputation runs once at CM exit
        with defer_rbac_computations():
            for i in range(n_teams):
                team = models.Team.objects.create(name=f'{ORG_DELETE_PREFIX}-team-{i}', organization=org)
                teams.append(team)
            usernames = [f'{ORG_DELETE_PREFIX}-user-t{i}-u{j}' for i in range(n_teams) for j in range(users_per_team)]
            User.objects.bulk_create([User(username=u) for u in usernames], ignore_conflicts=True)
            all_users = list(User.objects.filter(username__in=usernames))
            total_users = len(all_users)
            inventories = []
            n_inventories = max(1, n_teams // 2)
            for i in range(n_inventories):
                inv = models.Inventory.objects.create(name=f'{ORG_DELETE_PREFIX}-inv-{i}', organization=org)
                inventories.append(inv)

        # Assignments outside defer_rbac_computations
        for i, team in enumerate(teams):
            for user in all_users[i * users_per_team : (i + 1) * users_per_team]:
                member_rd.give_permission(user, team)

        n_org_admins = min(2, len(all_users))
        for user in all_users[:n_org_admins]:
            org_admin_rd.give_permission(user, org)

        for i, inv in enumerate(inventories):
            inv_admin_rd.give_permission(teams[i % len(teams)], inv)
            if i < len(all_users):
                inv_admin_rd.give_permission(all_users[i], inv)

    return Response(
        {
            'status': 'created',
            'org': org_name,
            'teams': n_teams,
            'users_per_team': users_per_team,
            'total_users': total_users,
            'org_admins': n_org_admins,
            'inventories': n_inventories,
        }
    )


@api_view(['GET'])
def org_delete_bare(request, format=None):
    org_name = f'{ORG_DELETE_PREFIX}-org'
    org = models.Organization.objects.filter(name=org_name).first()
    if not org:
        return Response({'error': f'Org "{org_name}" not found. Hit populate first.'}, status=404)

    org.delete()
    return Response({'status': 'deleted', 'mode': 'bare (no context managers)'})


@api_view(['GET'])
def org_delete_deferred(request, format=None):
    from ansible_base.rbac.triggers import defer_rbac_computations

    org_name = f'{ORG_DELETE_PREFIX}-org'
    org = models.Organization.objects.filter(name=org_name).first()
    if not org:
        return Response({'error': f'Org "{org_name}" not found. Hit populate first.'}, status=404)

    with defer_rbac_computations():
        org.delete()
    return Response({'status': 'deleted', 'mode': 'defer_rbac_computations only'})


@api_view(['GET'])
def org_delete_all_optimized(request, format=None):
    from ansible_base.activitystream import deferred_activity_stream
    from ansible_base.lib.utils.models import cached_system_user
    from ansible_base.rbac.triggers import defer_rbac_computations
    from ansible_base.resource_registry.signals.handlers import defer_resource_cleanup

    org_name = f'{ORG_DELETE_PREFIX}-org'
    org = models.Organization.objects.filter(name=org_name).first()
    if not org:
        return Response({'error': f'Org "{org_name}" not found. Hit populate first.'}, status=404)

    with cached_system_user(), deferred_activity_stream(), defer_resource_cleanup(), defer_rbac_computations():
        org.delete()
    return Response({'status': 'deleted', 'mode': 'all 4 context managers'})
