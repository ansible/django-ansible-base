from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response

from ansible_base.feature_flags.models import FeatureFlag
from ansible_base.feature_flags.serializers import FeatureFlagSerializer
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView

from .utils import get_feature_flags


class FeatureFlagsListView(AnsibleBaseView):
    """
    A view class for displaying feature flags
    """

    model = FeatureFlag
    serializer_class = FeatureFlagSerializer
    filter_backends = []
    name = _('Feature Flags')
    http_method_names = ['get', 'head']

    def get(self, request, format=None):
        return Response(get_feature_flags())

    def get_queryset(self):
        return get_feature_flags()


class FeatureFlagDetailView(AnsibleBaseView):
    """
    A view class for displaying feature flag detail
    """

    model = FeatureFlag
    serializer_class = FeatureFlagSerializer
    filter_backends = []
    name = _('Feature Flags')
    http_method_names = ['get', 'patch', 'head']

    def get(self, request, category_slug, format=None):
        self.serializer = FeatureFlagSerializer(category_slug)
        return Response(self.serializer.to_representation())

    def patch(self, request, category_slug, format=None):
        self.serializer = FeatureFlagSerializer(category_slug)
        updated_data = self.serializer.validate_and_save(request.data)
        return Response(updated_data)
