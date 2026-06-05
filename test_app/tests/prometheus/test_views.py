"""
Tests for MetricsView — content negotiation, auth, filtering, extra sources,
isolated registry, and multiprocess behaviour.
"""
import json

import pytest
from prometheus_client import CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Basic endpoint behaviour
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_200(client):
    response = client.get('/metrics/')
    assert response.status_code == 200


def test_metrics_endpoint_default_content_type(client):
    response = client.get('/metrics/')
    assert response['Content-Type'] == CONTENT_TYPE_LATEST


def test_metrics_endpoint_contains_request_metrics(client):
    client.get('/metrics/')
    response = client.get('/metrics/')
    content = response.content.decode()
    assert 'django_http_requests_total' in content
    assert 'django_http_request_duration_seconds' in content


def test_metrics_endpoint_contains_process_metrics(client):
    response = client.get('/metrics/')
    assert 'python_info' in response.content.decode()


def test_metrics_endpoint_multiprocess_skipped_without_dir(client, monkeypatch):
    monkeypatch.delenv('PROMETHEUS_MULTIPROC_DIR', raising=False)
    monkeypatch.delenv('prometheus_multiproc_dir', raising=False)
    response = client.get('/metrics/')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# JSON renderer (content negotiation)
# ---------------------------------------------------------------------------


def test_json_renderer_on_accept_header(client):
    response = client.get('/metrics/', HTTP_ACCEPT='application/json')
    assert response.status_code == 200
    assert 'application/json' in response['Content-Type']
    data = json.loads(response.content)
    assert isinstance(data, dict)


def test_json_renderer_structure(client):
    client.get('/metrics/')  # ensure at least one metric recorded
    response = client.get('/metrics/', HTTP_ACCEPT='application/json')
    data = json.loads(response.content)
    # prometheus_client strips _total from the family name when parsing, so the
    # JSON key is 'django_http_requests', not 'django_http_requests_total'.
    family = data.get('django_http_requests')
    assert family is not None, f"Key not found; available keys: {list(data)[:10]}"
    assert 'help' in family
    assert 'type' in family
    assert 'samples' in family
    assert isinstance(family['samples'], list)
    if family['samples']:
        sample = family['samples'][0]
        assert 'labels' in sample
        assert 'value' in sample
        assert 'timestamp' in sample


def test_text_renderer_is_default_when_no_accept_header(client):
    response = client.get('/metrics/')
    assert 'text/plain' in response['Content-Type']


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_anonymous_access_allowed_when_setting_is_true(client, settings):
    settings.ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS = True
    response = client.get('/metrics/')
    assert response.status_code == 200


def test_anonymous_access_denied_when_setting_is_false(client, settings):
    settings.ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS = False
    settings.ANSIBLE_PROMETHEUS_PERMISSION_CLASSES = ['rest_framework.permissions.IsAuthenticated']
    response = client.get('/metrics/')
    assert response.status_code in (401, 403)



def test_custom_permission_class_honoured(client, settings):
    settings.ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS = False
    settings.ANSIBLE_PROMETHEUS_PERMISSION_CLASSES = ['rest_framework.permissions.AllowAny']
    response = client.get('/metrics/')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# ?metric= query-param filtering
# ---------------------------------------------------------------------------


def test_metric_filter_returns_matching_family(client):
    client.get('/metrics/')  # ensure data exists
    # Filter on the HELP-line name, which includes _total for counters.
    response = client.get('/metrics/?metric=django_http_requests_total')
    content = response.content.decode()
    assert 'django_http_requests_total' in content
    # process metrics should be absent
    assert 'python_info' not in content


def test_metric_filter_empty_result_for_unknown_name(client):
    response = client.get('/metrics/?metric=this_metric_does_not_exist_xyz')
    assert response.content == b''


def test_metric_filter_partial_match(client):
    client.get('/metrics/')
    # 'django_http' appears in the HELP lines for both request counter and histogram.
    response = client.get('/metrics/?metric=django_http')
    content = response.content.decode()
    assert 'django_http' in content
    assert 'python_info' not in content


# ---------------------------------------------------------------------------
# EXTRA_SOURCES bridge
# ---------------------------------------------------------------------------


def test_extra_sources_output_is_appended(client, settings):
    def _fake_source(request):
        return b'# HELP fake_extra_metric A test metric\n# TYPE fake_extra_metric gauge\nfake_extra_metric 1.0\n'

    settings.ANSIBLE_PROMETHEUS_EXTRA_SOURCES = [f'{_fake_source.__module__}.{_fake_source.__qualname__}']

    # Patch via monkeypatching the import to avoid real dotted-path resolution
    import ansible_base.prometheus.views as views_module
    from django.utils.module_loading import import_string as real_import_string

    def patched_import_string(path):
        if path == f'{_fake_source.__module__}.{_fake_source.__qualname__}':
            return _fake_source
        return real_import_string(path)

    original = views_module.import_string
    views_module.import_string = patched_import_string
    try:
        response = client.get('/metrics/')
        assert 'fake_extra_metric' in response.content.decode()
    finally:
        views_module.import_string = original


def test_extra_sources_exception_is_swallowed(client, settings, caplog):
    import logging

    def _bad_source(request):
        raise RuntimeError("boom")

    import ansible_base.prometheus.views as views_module
    from django.utils.module_loading import import_string as real_import_string

    def patched_import_string(path):
        if 'bad_source' in path:
            return _bad_source
        return real_import_string(path)

    settings.ANSIBLE_PROMETHEUS_EXTRA_SOURCES = ['bad_source']
    original = views_module.import_string
    views_module.import_string = patched_import_string
    try:
        with caplog.at_level(logging.ERROR, logger='ansible_base.prometheus.views'):
            response = client.get('/metrics/')
        assert response.status_code == 200
        assert any('bad_source' in r.message for r in caplog.records)
    finally:
        views_module.import_string = original


# ---------------------------------------------------------------------------
# Isolated registry
# ---------------------------------------------------------------------------


def test_isolated_registry_excludes_process_metrics(client, settings):
    settings.ANSIBLE_PROMETHEUS_USE_ISOLATED_REGISTRY = True
    client.get('/metrics/')  # generate a request metric data point
    response = client.get('/metrics/')
    content = response.content.decode()
    assert 'django_http_requests_total' in content
    assert 'python_info' not in content


def test_isolated_registry_false_includes_process_metrics(client, settings):
    settings.ANSIBLE_PROMETHEUS_USE_ISOLATED_REGISTRY = False
    response = client.get('/metrics/')
    assert 'python_info' in response.content.decode()
