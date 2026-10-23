# observability

The `ansible_base.observability` app provides automatic OpenTelemetry instrumentation for Django applications. Adding it to `INSTALLED_APPS` wires up distributed tracing and log export with no additional code required.

Auto-instrumented libraries:

- Django (HTTP request spans)
- psycopg / psycopg2 (database spans)
- `requests` (outgoing HTTP spans)
- gRPC server
- Python `logging` (log records exported via OTLP)

## Settings

Install the optional dependencies:

```bash
pip install django-ansible-base[observability]
```

Add `ansible_base.observability` to your `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...
    'ansible_base.observability',
]
```

Configure the OTLP exporter logger in production to surface persistent failures while suppressing transient retry noise:

```python
LOGGING = {
    ...
    'loggers': {
        'opentelemetry.exporter.otlp.proto.grpc.exporter': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        ...
    },
}
```

`WARNING` passes through connection errors and permanent export failures while suppressing per-retry `DEBUG`/`INFO` chatter. Avoid `NullHandler` in production — the batch exporters drop telemetry silently when the collector is unreachable, and this logger is the only signal that the pipeline is broken.

For tests or environments where no collector is running, `NullHandler` is appropriate to suppress the expected retry errors:

```python
# test settings only
LOGGING = {
    ...
    'handlers': {
        'null': {'()': 'logging.NullHandler'},
        ...
    },
    'loggers': {
        'opentelemetry.exporter.otlp.proto.grpc.exporter': {
            'handlers': ['null'],
            'propagate': False,
        },
        ...
    },
}
```

## Additional Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `ANSIBLE_OBSERVABILITY_SERVICE_NAME` | Django setting | `"aap-generic"` | Service name attached to all spans and log records |
| `ANSIBLE_OBSERVABILITY_OTLP_ENDPOINT` | Django setting | `None` | OTLP collector endpoint (gRPC). Overrides `OTEL_EXPORTER_OTLP_ENDPOINT` env var |
| `ANSIBLE_OBSERVABILITY_BATCH_DELAY_MS` | Django setting | `5000` | Batch export delay in milliseconds for spans and log records |
| `ANSIBLE_OBSERVABILITY_CAPTURE_HEADERS` | Django setting | `[]` | List of header name patterns (regex) to capture as span attributes on both incoming and outgoing requests, and to forward from incoming Django requests to outgoing `requests`-library calls |

`OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_ENDPOINT` are standard OpenTelemetry environment variables. See the [OpenTelemetry SDK documentation](https://opentelemetry.io/docs/languages/python/exporters/) for the full list of supported env vars.

## Non-propagating loggers

Django applications commonly configure named loggers with `propagate = False` (e.g. `awx.main.tasks`). Those log records never reach the root logger and would normally be invisible to the OTLP log exporter.

The app detects these loggers at startup and attaches the OTLP `LoggingHandler` directly so their records still flow into the telemetry pipeline.

## Test span correlation

HTTP requests that include an `X-Test-Name` header have the value attached to their span as the `test.name` attribute. Outgoing `requests`-library calls made during that same request context automatically forward the header, propagating the test name across service boundaries.

This is useful when running integration tests against a live stack — spans in the collector can be filtered by `test.name` to isolate telemetry from a specific test case.

## Advanced usage

`setup_observability` can be called directly with custom exporters (useful in tests):

```python
from ansible_base.observability import setup_observability
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
setup_observability(service_name="my-service", span_exporter=exporter)
```

Parameters:

| Parameter | Default | Description |
|---|---|---|
| `service_name` | `OTEL_SERVICE_NAME` env var or `"aap-generic"` | Service name for the resource |
| `span_exporter` | `OTLPSpanExporter()` | Custom span exporter |
| `log_exporter` | `OTLPLogExporter()` | Custom log exporter |
| `instrument_non_propagating` | `True` | Attach handler to loggers with `propagate=False` |
