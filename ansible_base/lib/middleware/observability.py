"""
A single middleware to provide a unified observability layer, ensuring that context,
profiling, and SQL metrics are captured in the correct order.
"""

import logging

from django.conf import settings

from .profiling.profile_request import _ProfileRequestMiddleware, _SQLProfilingMiddleware
from .request_context import _TraceContextMiddleware

logger = logging.getLogger(__name__)

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

    Every request gets:
    - X-Request-ID (trace context)
    - X-API-Total-Time (wall-clock timing)

    cProfile and SQL metrics are individually gated:
    - ANSIBLE_BASE_PROFILING_ENABLED: .prof file generation + X-API-Profile-File header
    - ANSIBLE_BASE_PROFILING_SQL_ENABLED: SQL comment injection + X-API-Query-Count/Time headers

    Requests matching ANSIBLE_BASE_PROFILING_EXCLUDE_PATHS skip profiling features but
    still get trace context and timing.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Chain: _TraceContextMiddleware -> _ProfileRequestMiddleware -> _SQLProfilingMiddleware
        # _ProfileRequestMiddleware always adds timing; cProfile/SQL check their own flags.
        handler = _SQLProfilingMiddleware(get_response)
        handler = _ProfileRequestMiddleware(handler)
        self._handler = _TraceContextMiddleware(handler)

    def _is_excluded(self, path: str) -> bool:
        exclude_paths = getattr(settings, 'ANSIBLE_BASE_PROFILING_EXCLUDE_PATHS', DEFAULT_EXCLUDE_PATHS)
        return any(path.startswith(prefix) for prefix in exclude_paths)

    def __call__(self, request):
        if self._is_excluded(request.path):
            # Excluded paths still get trace context and timing, but
            # skip profiling even if the flags are on.
            request._profiling_excluded = True
        return self._handler(request)
