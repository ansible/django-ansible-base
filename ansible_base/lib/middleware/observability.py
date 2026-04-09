"""
A single middleware to provide a unified observability layer, ensuring that context,
profiling, and SQL metrics are captured in the correct order.
"""

import logging

from django.conf import settings

from .profiling.profile_request import _ProfileRequestMiddleware, _SQLProfilingMiddleware
from .request_context import _TraceContextMiddleware

logger = logging.getLogger(__name__)

PROFILING_SETTING = 'PROFILING_ENABLED'
PROFILING_EXCLUDE_PATHS_SETTING = 'PROFILING_EXCLUDE_PATHS'

DEFAULT_EXCLUDE_PATHS = [
    '/api/gateway/v1/ping/',
    '/up',
    '/v3/discovery:',
]


class ObservabilityMiddleware:
    """
    A single entry point for observability middleware.

    This middleware composes the trace context, request profiling, and SQL
    profiling middleware in the correct order. Instead of listing all three
    in your settings, you can now just add this one.

    The profiling and SQL layers are gated behind the PROFILING_ENABLED
    setting. When disabled, only trace context is applied (request ID
    tracking), and the profiling layers short-circuit with zero overhead.
    Changing this setting requires a restart.

    Requests matching PROFILING_EXCLUDE_PATHS are always skipped, even when
    profiling is enabled. This filters out health checks, discovery, and
    other internal traffic.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Chain the middleware in the desired order. The request will flow
        # from _TraceContextMiddleware -> _ProfileRequestMiddleware -> _SQLProfilingMiddleware.
        handler = _SQLProfilingMiddleware(get_response)
        handler = _ProfileRequestMiddleware(handler)
        self._profiling_handler = _TraceContextMiddleware(handler)
        # Lightweight handler for when profiling is disabled (trace context only)
        self._trace_only_handler = _TraceContextMiddleware(get_response)

    def _is_excluded(self, path: str) -> bool:
        exclude_paths = getattr(settings, PROFILING_EXCLUDE_PATHS_SETTING, DEFAULT_EXCLUDE_PATHS)
        return any(path.startswith(prefix) for prefix in exclude_paths)

    def __call__(self, request):
        if not getattr(settings, PROFILING_SETTING, False) or self._is_excluded(request.path):
            return self._trace_only_handler(request)
        return self._profiling_handler(request)
