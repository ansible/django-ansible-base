"""
A single middleware to provide a unified observability layer, ensuring that context,
profiling, and SQL metrics are captured in the correct order.
"""

from .profiling.profile_request import _ProfileRequestMiddleware, _SQLProfilingMiddleware
from .request_context import _TraceContextMiddleware


class ObservabilityMiddleware:
    """
    A single entry point for observability middleware.

    This middleware composes the trace context, request profiling, and SQL
    profiling middleware in the correct order. Instead of listing all three
    in your settings, you can now just add this one.
    """

    def __init__(self, get_response):
        # Chain the middleware in the desired order. The request will flow
        # from _TraceContextMiddleware -> _ProfileRequestMiddleware -> _SQLProfilingMiddleware.
        handler = _SQLProfilingMiddleware(get_response)
        handler = _ProfileRequestMiddleware(handler)
        self.handler = _TraceContextMiddleware(handler)

    def __call__(self, request):
        return self.handler(request)
