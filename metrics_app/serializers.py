from rest_framework.serializers import ModelSerializer

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.rbac.api.related import RelatedAccessMixin
from metrics_app import models


class MetricsSerializer(RelatedAccessMixin, NamedCommonModelSerializer):
    class Meta:
        model = models.Metric
        fields = '__all__'