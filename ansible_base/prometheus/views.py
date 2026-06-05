"""
Prometheus metrics endpoint.

MetricsView is a DRF APIView that:
  - negotiates text/plain (for Prometheus scrapers) and application/json
  - enforces configurable permissions (default: IsAuthenticated, bypass with
    ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS = True)
  - aggregates output from the local registry and any ANSIBLE_PROMETHEUS_EXTRA_SOURCES
  - supports ?metric=<name> query-param filtering on the final text output
"""
import logging
import os

from django.conf import settings
from django.utils.module_loading import import_string
from prometheus_client import REGISTRY, generate_latest
from rest_framework.response import Response
from rest_framework.views import APIView

from .renderers import PrometheusJSONRenderer, PrometheusTextRenderer

logger = logging.getLogger(__name__)


def _build_registry():
    """Return the CollectorRegistry that generate_latest() should use."""
    if os.environ.get('PROMETHEUS_MULTIPROC_DIR') or os.environ.get('prometheus_multiproc_dir'):
        from prometheus_client import CollectorRegistry
        from prometheus_client.multiprocess import MultiProcessCollector

        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        return registry

    if getattr(settings, 'ANSIBLE_PROMETHEUS_USE_ISOLATED_REGISTRY', False):
        # Only expose metrics registered via DAB's helpers, not the default
        # process/platform collectors. Matches AWX's isolated-registry behaviour.
        from prometheus_client import CollectorRegistry

        from ansible_base.prometheus.registry import _registry as dab_metrics

        registry = CollectorRegistry()
        for metric in dab_metrics.values():
            registry.register(metric)
        return registry

    return REGISTRY


def _filter_by_metric_name(text: bytes, name_filter: str) -> bytes:
    """Keep only metric families whose name contains name_filter."""
    result = []
    include = False
    for line in text.decode().splitlines(keepends=True):
        if line.startswith('# HELP '):
            family_name = line.split(' ', 3)[2]
            include = name_filter in family_name
        if include:
            result.append(line)
    return ''.join(result).encode()


class MetricsView(APIView):
    """Expose Prometheus metrics for scraping.

    Content negotiation:
      - ``Accept: text/plain`` (or no Accept header) → Prometheus text format
      - ``Accept: application/json``                  → structured JSON

    Settings:
      ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS (bool, default False)
          Allow unauthenticated access. Set True when Prometheus scrapes without
          credentials, or protect the endpoint at the network level instead.

      ANSIBLE_PROMETHEUS_PERMISSION_CLASSES (list[str])
          Dotted-path DRF permission classes used when anonymous access is
          disabled. Defaults to ['rest_framework.permissions.IsAuthenticated'].
          Override to enforce superuser / auditor checks (e.g. in AWX).

      ANSIBLE_PROMETHEUS_EXTRA_SOURCES (list[str])
          Dotted-path callables invoked as ``fn(request) -> bytes``. Each must
          return valid Prometheus text-format bytes. Their output is appended to
          the local registry output before filtering. Use this to bridge
          subsystem metrics (Redis-backed, multi-node, external processes) into
          the endpoint without modifying DAB.

      ANSIBLE_PROMETHEUS_USE_ISOLATED_REGISTRY (bool, default False)
          When True, only metrics registered via DAB's helpers are exposed.
          The default process/platform collectors (python_info, process_*) are
          omitted. Matches AWX's isolated CollectorRegistry behaviour.

    Query parameters:
      metric=<name>
          Return only metric families whose name contains the given string.
          Applied after extra-source output is appended.
    """

    renderer_classes = [PrometheusTextRenderer, PrometheusJSONRenderer]

    def get_permissions(self):
        if getattr(settings, 'ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS', False):
            from rest_framework.permissions import AllowAny

            return [AllowAny()]
        classes = getattr(
            settings,
            'ANSIBLE_PROMETHEUS_PERMISSION_CLASSES',
            ['rest_framework.permissions.IsAuthenticated'],
        )
        return [import_string(cls)() for cls in classes]

    def get(self, request):
        output = generate_latest(_build_registry())

        for source_path in getattr(settings, 'ANSIBLE_PROMETHEUS_EXTRA_SOURCES', []):
            try:
                output += import_string(source_path)(request)
            except Exception:
                logger.exception("Failed to collect metrics from extra source %s", source_path)

        if name_filter := request.query_params.get('metric'):
            output = _filter_by_metric_name(output, name_filter)

        return Response(output)


# Backward-compatible function alias so existing url confs keep working.
metrics_view = MetricsView.as_view()
