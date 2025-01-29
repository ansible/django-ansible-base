from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response

from ansible_base.feature_flags.serializers import FeatureFlagSerializer
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView

from .utils import get_django_flags


class FeatureFlagsStateListView(AnsibleBaseView):
    """
    A view class for displaying feature flags
    """

    serializer_class = FeatureFlagSerializer
    filter_backends = []
    name = _('Feature Flags')
    http_method_names = ['get', 'head']

    def get(self, request, format=None):
        self.serializer = FeatureFlagSerializer()
        return Response(self.serializer.to_representation())

    def get_queryset(self):
        return get_django_flags()
