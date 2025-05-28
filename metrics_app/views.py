from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from metrics_app import models, serializers

# Create your views here.
class MetricsViewSet(ModelViewSet, AnsibleBaseView):
    serializer_class = serializers.MetricSerializer
    queryset = models.Metrics.objects.all()
