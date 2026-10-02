# Prometheus Metrics App

`ansible_base.prometheus` exposes a `/metrics` endpoint for Prometheus scraping and provides a
thread-safe API for any Django app to register its own custom metrics.

## Installation

```bash
pip install django-ansible-base[prometheus]
```

## Setup

### 1. Add to INSTALLED_APPS

```python
INSTALLED_APPS = [
    ...
    'ansible_base.prometheus',
]
```

`PrometheusConfig.ready()` calls `setup_prometheus()` automatically on startup.

### 2. Add the middleware

```python
MIDDLEWARE = [
    ...
    'ansible_base.prometheus.middleware.PrometheusMiddleware',
]
```

This records `django_http_requests_total` (Counter) and `django_http_request_duration_seconds`
(Histogram), both labelled by `method`, `view`, and `status_code`.

### 3. Expose the /metrics URL

Include the app's URL conf from your root `urls.py`:

```python
from django.urls import include, path

urlpatterns = [
    ...
    path('', include('ansible_base.prometheus.urls')),
]
```

This registers `/metrics/` by default. Override the path with `ANSIBLE_PROMETHEUS_METRICS_PATH`
(see [Configuration](#configuration)).

## Authentication

By default the endpoint requires authentication (`IsAuthenticated`). To allow unauthenticated
scraping (e.g. when Prometheus scrapes without credentials and the endpoint is network-protected):

```python
ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS = True
```

To enforce a custom permission policy (e.g. superuser or auditor only, as AWX does):

```python
ANSIBLE_PROMETHEUS_PERMISSION_CLASSES = [
    'myapp.permissions.IsSuperuserOrAuditor',
]
```

Any [DRF permission class](https://www.django-rest-framework.org/api-guide/permissions/) is valid.

## Content negotiation

| Accept header | Response format |
|---|---|
| `text/plain` (default, used by Prometheus scrapers) | Prometheus text exposition format |
| `application/json` | Structured JSON — metric family per key, list of samples with `labels`, `value`, `timestamp` |

The browsable DRF API (HTML) is also available when `rest_framework` renders it.

## Query parameters

| Parameter | Example | Effect |
|---|---|---|
| `metric` | `?metric=django_http` | Return only metric families whose `# HELP` line contains the given string |

```bash
# Only HTTP request metrics
curl /metrics/?metric=django_http_requests_total

# Only a specific app's metrics
curl /metrics/?metric=myapp_
```

## Custom metrics per app

Each Django app can define its own metrics using the helpers from `ansible_base.prometheus`.
Define them at **module level** so they are registered once on first import:

```python
# myapp/metrics.py
from ansible_base.prometheus import counter, gauge, histogram, summary

login_attempts = counter(
    'myapp_login_attempts_total',
    'Total login attempts',
    labels=['outcome'],   # 'success' | 'failure'
)

active_sessions = gauge(
    'myapp_active_sessions',
    'Number of currently active sessions',
)

job_duration = histogram(
    'myapp_job_duration_seconds',
    'Job execution time in seconds',
    labels=['job_type'],
    buckets=[0.1, 0.5, 1.0, 5.0, 30.0, 60.0],
)
```

Then use them anywhere in your app:

```python
from myapp.metrics import login_attempts, job_duration

def login(request):
    ...
    login_attempts.labels(outcome='success').inc()
```

### Available helpers

| Helper | prometheus_client type | Notes |
|--------|----------------------|-------|
| `counter(name, doc, labels)` | `Counter` | Monotonically increasing |
| `gauge(name, doc, labels)` | `Gauge` | Can go up or down |
| `histogram(name, doc, labels, buckets)` | `Histogram` | Configurable buckets |
| `summary(name, doc, labels)` | `Summary` | Quantile estimation |

All helpers are **idempotent**: calling them twice with the same name returns the existing metric
instead of raising `ValueError`.

## Bridging external metric sources

Use `ANSIBLE_PROMETHEUS_EXTRA_SOURCES` to append Prometheus text format output from other
subsystems — Redis-backed cluster metrics, external process scrapers, or any source that can't
register into the global registry at startup time:

```python
# settings.py
ANSIBLE_PROMETHEUS_EXTRA_SOURCES = [
    'myapp.analytics.subsystem_metrics.get_cluster_metrics',
    'myapp.analytics.dispatcherd_metrics.get_dispatcherd_metrics',
]
```

Each entry is a dotted-path callable with signature `fn(request: Request) -> bytes` that returns
valid Prometheus text format. Errors in individual sources are logged and skipped so that a
failing subsystem doesn't take down the whole endpoint.

```python
# myapp/analytics/subsystem_metrics.py
def get_cluster_metrics(request) -> bytes:
    node_filter = request.query_params.get('node')
    # ... aggregate metrics from Redis ...
    return prometheus_text_bytes
```

## Configuration reference

| Setting | Default | Description |
|---------|---------|-------------|
| `ANSIBLE_PROMETHEUS_METRICS_PATH` | `'metrics/'` | URL path for the endpoint |
| `ANSIBLE_PROMETHEUS_ALLOW_ANONYMOUS` | `False` | Allow unauthenticated access |
| `ANSIBLE_PROMETHEUS_PERMISSION_CLASSES` | `['rest_framework.permissions.IsAuthenticated']` | DRF permission classes when anonymous is disabled |
| `ANSIBLE_PROMETHEUS_EXTRA_SOURCES` | `[]` | Additional metric source callables |
| `ANSIBLE_PROMETHEUS_USE_ISOLATED_REGISTRY` | `False` | Exclude default process/platform metrics from the output |
| `ANSIBLE_PROMETHEUS_MULTIPROC_DIR` | `None` | Path to the multiprocess metrics directory (see below) |

## Isolated registry

When `ANSIBLE_PROMETHEUS_USE_ISOLATED_REGISTRY = True`, only metrics registered via DAB's
helpers are exposed. The default process and Python runtime collectors (`python_info`,
`process_cpu_seconds_total`, etc.) are omitted. Useful when the consuming service controls
exactly what appears in the scrape output.

## Multiprocess environments (Gunicorn / uWSGI)

When running with multiple worker processes each worker holds its own counters. The endpoint
automatically merges them when `PROMETHEUS_MULTIPROC_DIR` is set:

```python
# settings.py
ANSIBLE_PROMETHEUS_MULTIPROC_DIR = '/tmp/prometheus_multiproc'
```

Or set the env var directly before starting workers:

```bash
export PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
gunicorn myapp.wsgi
```

See the [prometheus_client multiprocess docs](https://prometheus.github.io/client_python/multiprocess/)
for the full worker lifecycle requirements.

## Mounting at a custom path (AWX migration example)

AWX exposes metrics at `/api/v2/metrics/`. To migrate to DAB while keeping the same URL:

```python
# settings.py
ANSIBLE_PROMETHEUS_METRICS_PATH = 'api/v2/metrics/'

# urls.py
urlpatterns = [
    ...
    path('', include('ansible_base.prometheus.urls')),
]
```

AWX-specific metrics (`awx_organizations_total`, `awx_running_jobs_total`, etc.) stay in AWX and
are registered using DAB's `counter()` / `gauge()` helpers in AWX's `AppConfig.ready()`. Subsystem
metrics (task manager, callback receiver) are bridged via `ANSIBLE_PROMETHEUS_EXTRA_SOURCES`.

## Built-in metrics

| Metric | Type | Labels | Source |
|---|---|---|---|
| `django_http_requests_total` | Counter | `method`, `view`, `status_code` | `PrometheusMiddleware` |
| `django_http_request_duration_seconds` | Histogram | `method`, `view` | `PrometheusMiddleware` |
| `process_cpu_seconds_total` | Counter | — | prometheus_client (automatic) |
| `process_open_fds` | Gauge | — | prometheus_client (automatic) |
| `process_resident_memory_bytes` | Gauge | — | prometheus_client (automatic) |
| `python_info` | Info | `version`, `implementation` | prometheus_client (automatic) |
| `python_gc_objects_collected_total` | Counter | `generation` | prometheus_client (automatic) |

Process/platform metrics are excluded when `ANSIBLE_PROMETHEUS_USE_ISOLATED_REGISTRY = True`.
