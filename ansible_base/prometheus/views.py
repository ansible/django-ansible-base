import os

from django.http import HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest


def metrics_view(request):
    """Expose Prometheus metrics for scraping.

    In multiprocess environments (Gunicorn/uWSGI) set PROMETHEUS_MULTIPROC_DIR
    (or ANSIBLE_PROMETHEUS_MULTIPROC_DIR in Django settings) so that per-worker
    metric files are merged before being returned.
    """
    if os.environ.get('PROMETHEUS_MULTIPROC_DIR') or os.environ.get('prometheus_multiproc_dir'):
        from prometheus_client import CollectorRegistry
        from prometheus_client.multiprocess import MultiProcessCollector

        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        output = generate_latest(registry)
    else:
        output = generate_latest(REGISTRY)

    return HttpResponse(output, content_type=CONTENT_TYPE_LATEST)
