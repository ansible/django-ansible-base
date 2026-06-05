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

This registers `/metrics/` (the standard Prometheus scrape path).

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
from myapp.metrics import login_attempts, active_sessions, job_duration

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

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `ANSIBLE_PROMETHEUS_MULTIPROC_DIR` | `None` | Path to the multiprocess metrics directory (see below) |

## Multiprocess environments (Gunicorn / uWSGI)

When running with multiple worker processes each worker holds its own counters. The `/metrics`
view automatically merges them when `PROMETHEUS_MULTIPROC_DIR` is set:

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

## Built-in metrics

In addition to the HTTP metrics added by `PrometheusMiddleware`, `prometheus_client` registers
process and Python runtime metrics automatically:

- `process_cpu_seconds_total`
- `process_open_fds`
- `process_resident_memory_bytes`
- `python_info`
- `python_gc_objects_collected_total`
