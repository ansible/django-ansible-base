import pytest

from ansible_base.prometheus.middleware import _REQUEST_COUNT, _REQUEST_LATENCY


@pytest.fixture
def count_before(client):
    """Return request count for a given label-set before making a request."""

    def _before(method, view, status_code):
        try:
            return _REQUEST_COUNT.labels(method=method, view=view, status_code=status_code)._value.get()
        except KeyError:
            return 0.0

    return _before


def test_middleware_increments_request_count(client, count_before):
    before = count_before('GET', 'prometheus-metrics', '200')
    client.get('/metrics/')
    after = _REQUEST_COUNT.labels(method='GET', view='prometheus-metrics', status_code='200')._value.get()
    assert after == before + 1


def test_middleware_records_latency(client):
    client.get('/metrics/')
    assert _REQUEST_LATENCY.labels(method='GET', view='prometheus-metrics')._sum.get() > 0


def test_middleware_tracks_method(client):
    before = _REQUEST_COUNT.labels(method='GET', view='prometheus-metrics', status_code='200')._value.get()
    client.get('/metrics/')
    after = _REQUEST_COUNT.labels(method='GET', view='prometheus-metrics', status_code='200')._value.get()
    assert after > before


def test_middleware_unknown_view(rf):
    from django.http import HttpResponse

    from ansible_base.prometheus.middleware import PrometheusMiddleware

    def get_response(request):
        return HttpResponse(status=404)

    middleware = PrometheusMiddleware(get_response)
    request = rf.get('/nonexistent/')
    # resolver_match is not set — view should fall back to 'unknown'
    response = middleware(request)
    assert response.status_code == 404
    assert _REQUEST_COUNT.labels(method='GET', view='unknown', status_code='404')._value.get() >= 1
