import logging
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.response import get_fully_qualified_url
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.rbac import permission_registry
from ansible_base.rbac.policies import visible_users
from metrics_app import models, serializers

logger = logging.getLogger(__name__)


class MetricsAppViewSet(ModelViewSet, AnsibleBaseView):
    prefetch_related = ()
    select_related = ()

    def apply_optimizations(self, qs):
        if self.prefetch_related:
            qs = qs.prefetch_related(*self.prefetch_related)
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        return qs
    
class MetricsViewSet(MetricsAppViewSet):
    serializer_class = serializers.MetricsSerializer
    prefetch_related = ('created_by', 'modified_by', 'resource', 'resource__content_type')
    queryset = models.Metric.objects.all()
