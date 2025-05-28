from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from metrics_app import models

class MetricSerializer(NamedCommonModelSerializer):
  class Meta:
    model = models.Metrics
    fields = "__all__"
