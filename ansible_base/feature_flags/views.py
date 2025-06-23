from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.feature_flags.serializers import FeatureFlagStatesSerializer, OldFeatureFlagSerializer
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor, try_add_oauth2_scope_permission

from .utils import get_django_flags


class FeatureFlagsStatesView(AnsibleBaseDjangoAppApiView, ModelViewSet):
    """
    A view class for displaying feature flags states.
    To add/update/remove a feature flag, see the instructions in
    `docs/apps/feature_flags.md`
    """

    queryset = AAPFlag.objects.order_by('id')
    permission_classes = try_add_oauth2_scope_permission([IsSuperuserOrAuditor])
    serializer_class = FeatureFlagStatesSerializer
    http_method_names = ['get', 'head', 'options']


# TODO: This can be removed after functionality is migrated over to new class
class OldFeatureFlagsStateListView(AnsibleBaseView):
    """
    A view class for displaying feature flags
    """

    serializer_class = OldFeatureFlagSerializer
    filter_backends = []
    name = _('Feature Flags')
    http_method_names = ['get', 'head']

    def _get(self, request, format=None):
        self.serializer = OldFeatureFlagSerializer()
        return Response(self.serializer.to_representation())

    def get_queryset(self):
        return get_django_flags()

    # Conditionally add openapi documentation for feature flags
    if 'ansible_base.api_documentation' in settings.INSTALLED_APPS:
        from drf_spectacular.types import OpenApiTypes
        from drf_spectacular.utils import OpenApiExample, extend_schema

        @extend_schema(request=None, responses=OpenApiTypes.OBJECT, examples=[OpenApiExample(name="featureflags", value={"FLAG1": True, "FLAG2": False})])
        def get(self, request, format=None):
            return self._get(request, format)

    else:

        def get(self, request, format=None):
            return self._get(request, format)
