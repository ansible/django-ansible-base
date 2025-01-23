from django.http import HttpResponseNotFound
from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response

from ansible_base.feature_flags.models import FeatureFlag
from ansible_base.feature_flags.serializers import FeatureFlagSerializer
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView

from .utils import get_django_flags


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
        return Response(get_django_flags())

    def get_queryset(self):
        return get_django_flags()


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
        if self.serializer.to_representation() == {}:
            return HttpResponseNotFound()
        return Response(self.serializer.to_representation())
