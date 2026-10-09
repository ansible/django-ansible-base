import time

from ansible_base.prometheus.registry import counter, histogram

# Module-level singletons — registered once, shared across all requests.
_REQUEST_COUNT = counter(
    'django_http_requests_total',
    'Total HTTP requests received',
    labels=['method', 'view', 'status_code'],
)

_REQUEST_LATENCY = histogram(
    'django_http_request_duration_seconds',
    'HTTP request latency in seconds',
    labels=['method', 'view'],
)


class PrometheusMiddleware:
    """Records per-request HTTP metrics for Prometheus scraping.

    Add to MIDDLEWARE after the URL resolver middleware so that
    request.resolver_match is populated before metrics are recorded:

        MIDDLEWARE = [
            ...
            'ansible_base.prometheus.middleware.PrometheusMiddleware',
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration = time.monotonic() - start

        view_name = 'unknown'
        if resolver_match := getattr(request, 'resolver_match', None):
            view_name = resolver_match.view_name or 'unknown'

        _REQUEST_COUNT.labels(
            method=request.method,
            view=view_name,
            status_code=str(response.status_code),
        ).inc()
        _REQUEST_LATENCY.labels(
            method=request.method,
            view=view_name,
        ).observe(duration)

        return response
