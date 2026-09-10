import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


def setup_prometheus() -> None:
    """Configure Prometheus metrics collection for a Django application.

    Called once at application startup via PrometheusConfig.ready(). Applies the
    multiprocess directory setting and warns when PrometheusMiddleware is absent.

    Like setup_observability(), this is intentionally NOT idempotent — calling it
    a second time would emit duplicate warnings and override env vars that may have
    already been inherited by worker processes.
    """
    if multiproc_dir := getattr(settings, 'ANSIBLE_PROMETHEUS_MULTIPROC_DIR', None):
        os.environ.setdefault('PROMETHEUS_MULTIPROC_DIR', str(multiproc_dir))

    middleware = getattr(settings, 'MIDDLEWARE', [])
    if 'ansible_base.prometheus.middleware.PrometheusMiddleware' not in middleware:
        logger.warning(
            "ansible_base.prometheus is installed but PrometheusMiddleware is not in MIDDLEWARE. "
            "HTTP request metrics will not be collected. Add "
            "'ansible_base.prometheus.middleware.PrometheusMiddleware' to MIDDLEWARE."
        )
