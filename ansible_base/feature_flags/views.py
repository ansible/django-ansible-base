from django.utils.translation import gettext_lazy as _
from flags.state import flag_enabled
from rest_framework import viewsets

from ansible_base.feature_flags.models import FeatureFlag

# from ansible_base.feature_flags.serializers import FeatureFlagSerializer
from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView


class FeatureFlagView(viewsets.ModelViewSet, AnsibleBaseView):
    """
    A view class for displaying feature flags
    """

    model = FeatureFlag
    # serializer_class = FeatureFlagSerializer
    filter_backends = []
    name = _('Feature Flags')
    http_method_names = ['get', 'head']

    def get_queryset(self):
        platform_flags = get_setting('FLAGS', {})
        service_flags = get_setting('ANSIBLE_BASE_SERVICE_FEATURE_FLAGS', {})

        platform_flags.update(service_flags)

        response = {}
        all_flags = platform_flags.keys()
        for flag in sorted(all_flags):
            response[flag] = flag_enabled(flag)

        return response
