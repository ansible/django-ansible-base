from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from flags.state import flag_enabled, flag_state, get_flags
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.feature_flags.serializers import FeatureFlagSerializer, OldFeatureFlagSerializer
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.rest_pagination import DefaultPaginator

from .utils import get_django_flags, is_boolean_str


class FeatureFlagsView(AnsibleBaseDjangoAppApiView, ModelViewSet):
    """
    A view class for displaying feature flags
    """

    resource_purpose = "feature flag configurations for controlling platform capabilities"

    queryset = AAPFlag.objects.order_by('id')
    serializer_class = FeatureFlagSerializer
    permission_classes = [IsSuperuserOrAuditor]
    http_method_names = ['get', 'put', 'head', 'options']

    def update(self, request, **kwargs):
        _feature_flag = self.get_object()
        value = request.data.get('value')
        if not value:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": "Invalid request object."})

        # Disable runtime toggle if the feature flag feature is not enabled
        if not flag_enabled('FEATURE_FEATURE_FLAGS_ENABLED'):
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED, data={"details": "Runtime feature flags toggle is not enabled."})

        feature_flag = get_object_or_404(AAPFlag, pk=_feature_flag.id)
        if feature_flag.toggle_type == 'install-time':
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED, data={"details": "Install-time feature flags cannot be toggled at run-time."})
        if feature_flag.condition == "boolean" and not is_boolean_str(value):
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": "Feature flag boolean conditional requires using boolean value."})
        feature_flag.value = value
        feature_flag.save()

        return Response(self.get_serializer().to_representation(feature_flag))


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
