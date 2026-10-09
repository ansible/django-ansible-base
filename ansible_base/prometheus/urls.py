from django.conf import settings
from django.urls import path

from .views import MetricsView

# Allow consuming services to mount at a different path (e.g. 'api/v2/metrics/')
# without having to re-define the URL themselves.
_path = getattr(settings, 'ANSIBLE_PROMETHEUS_METRICS_PATH', 'metrics/')

urlpatterns = [
    path(_path, MetricsView.as_view(), name='prometheus-metrics'),
]
